from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from .errors import AnalysisError
from .io import write_json
from .models import AnalysisBundle

SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
EXCLUDED_DIRS = {".git", "build", "dist", "third_party", "vendor", "node_modules"}
INCLUDE_RE = re.compile(r'^\s*#\s*include\s*(?P<quote>[<"])(?P<target>[^>"]+)[>"]', re.M)
MACRO_RE = re.compile(r'^\s*#\s*define\s+(?P<name>[A-Za-z_]\w*)', re.M)
TYPE_RE = re.compile(r'\b(?P<kind>struct|class|enum)\s+(?P<name>[A-Za-z_]\w*)', re.M)
FUNCTION_RE = re.compile(
    r'(?m)^[ \t]*(?P<signature>(?:[\w:*&]+[ \t]+)+(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^;{}]*)\)\s*\{)'
)
CALL_RE = re.compile(r'\b(?P<name>[A-Za-z_]\w*)\s*\(')
CONTROL_WORDS = {"if", "for", "while", "switch", "return", "sizeof", "catch"}


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _closing_brace(text: str, opening: int) -> int:
    level = 0
    in_string = False
    quote = ""
    escape = False
    for index in range(opening, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                in_string = False
            continue
        if char in {"'", '"'}:
            in_string, quote = True, char
        elif char == "{":
            level += 1
        elif char == "}":
            level -= 1
            if level == 0:
                return index
    return len(text) - 1


class ClangAnalyzer:
    """Runs the bundled LibTooling executable and enriches its facts conservatively."""

    def __init__(self, executable: str | Path | None = None) -> None:
        self.executable = Path(executable).expanduser() if executable else None

    def analyze(self, repo: Path, compilation_database: Path, output_dir: Path) -> AnalysisBundle:
        output_dir.mkdir(parents=True, exist_ok=True)
        compiler = self._resolve_executable()
        bundle = AnalysisBundle(mode="partial")
        if compiler is not None:
            try:
                self._run_libtooling(compiler, repo, compilation_database, bundle)
                bundle.mode = "full"
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError, AnalysisError) as exc:
                bundle.diagnostics.append(f"LibTooling analyzer failed; lexical augmentation used: {exc}")
        else:
            bundle.diagnostics.append(
                "cpp-analyzer 未找到；使用词法辅助分析。该模式不提供编译器级语义保证。"
            )
        self._lexical_augment(repo, bundle)
        self._deduplicate(bundle)
        self._write_artifacts(output_dir, bundle)
        return bundle

    def _resolve_executable(self) -> Path | None:
        if self.executable and self.executable.is_file():
            return self.executable.resolve()
        found = shutil.which("clangwiki-analyzer") or shutil.which("cpp-analyzer")
        return Path(found) if found else None

    def _run_libtooling(self, executable: Path, repo: Path, compdb: Path, bundle: AnalysisBundle) -> None:
        entries = json.loads(compdb.read_text(encoding="utf-8"))
        units = []
        for item in entries:
            source = Path(item["file"])
            source = source if source.is_absolute() else Path(item["directory"]) / source
            if source.exists():
                units.append(str(source.resolve()))
        if not units:
            raise AnalysisError("compile_commands.json 中没有可访问的翻译单元。")
        process = subprocess.run(
            [str(executable), "-p", str(compdb.parent), "--repo-root", str(repo), *units],
            cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=900, check=False,
        )
        if process.returncode != 0:
            raise AnalysisError(process.stderr.strip() or f"exit code {process.returncode}")
        for raw in process.stdout.splitlines():
            if not raw.strip():
                continue
            record = json.loads(raw)
            if record.get("record") == "symbol":
                bundle.symbols.append(record)
            elif record.get("record") == "relation":
                bundle.relations.append(record)

    def _lexical_augment(self, repo: Path, bundle: AnalysisBundle) -> None:
        existing_files = {row.get("file_path") for row in bundle.symbols}
        for path in sorted(repo.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(repo).as_posix()
            if any(part in EXCLUDED_DIRS for part in path.relative_to(repo).parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                bundle.diagnostics.append(f"Cannot read {relative}: {exc}")
                continue
            bundle.files.append({"path": relative, "language": path.suffix.lower(), "source": "filesystem"})
            for match in INCLUDE_RE.finditer(text):
                bundle.relations.append({"source": relative, "target": match.group("target"),
                    "kind": "INCLUDES", "file_path": relative, "line": _line(text, match.start()),
                    "confidence": 1.0, "certainty": "lexical"})
            for match in MACRO_RE.finditer(text):
                bundle.symbols.append(self._symbol("macro", match.group("name"), relative,
                    _line(text, match.start()), _line(text, match.end()), match.group(0).strip(), "lexical"))
            for match in TYPE_RE.finditer(text):
                bundle.symbols.append(self._symbol(match.group("kind"), match.group("name"), relative,
                    _line(text, match.start()), _line(text, match.end()), match.group(0).strip(), "lexical"))
            for match in FUNCTION_RE.finditer(text):
                name = match.group("name")
                opening = text.find("{", match.start(), match.end())
                closing = _closing_brace(text, opening)
                start_line, end_line = _line(text, match.start()), _line(text, closing)
                symbol = self._symbol("function", name, relative, start_line, end_line,
                    match.group("signature").rstrip("{").strip(), "lexical")
                symbol["parameters"] = [item.strip() for item in match.group("params").split(",") if item.strip()]
                bundle.symbols.append(symbol)
                body = text[opening + 1:closing]
                for call in CALL_RE.finditer(body):
                    callee = call.group("name")
                    if callee not in CONTROL_WORDS:
                        bundle.relations.append({"source": name, "target": callee, "kind": "POSSIBLE_CALL",
                            "file_path": relative, "line": _line(text, opening + 1 + call.start()),
                            "confidence": 0.5, "certainty": "lexical"})

    @staticmethod
    def _symbol(kind: str, name: str, file_path: str, start: int, end: int,
                signature: str, certainty: str) -> dict[str, object]:
        return {"kind": kind, "name": name, "qualified_name": name, "file_path": file_path,
                "line_start": start, "line_end": end, "signature": signature, "certainty": certainty}

    @staticmethod
    def _deduplicate(bundle: AnalysisBundle) -> None:
        def unique(rows: Iterable[dict[str, object]], fields: tuple[str, ...]) -> list[dict[str, object]]:
            result, seen = [], set()
            for row in rows:
                key = tuple(row.get(field) for field in fields)
                if key not in seen:
                    result.append(row)
                    seen.add(key)
            return result
        bundle.files = unique(bundle.files, ("path",))
        bundle.symbols = unique(bundle.symbols, ("kind", "qualified_name", "file_path", "line_start"))
        bundle.relations = unique(bundle.relations, ("source", "target", "kind", "file_path", "line"))

    @staticmethod
    def _write_artifacts(output_dir: Path, bundle: AnalysisBundle) -> None:
        write_json(output_dir / "files.json", bundle.files)
        write_json(output_dir / "symbols.json", bundle.symbols)
        write_json(output_dir / "relations.json", bundle.relations)
        write_json(output_dir / "diagnostics.json", {"mode": bundle.mode, "diagnostics": bundle.diagnostics})
