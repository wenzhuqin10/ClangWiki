from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
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
ANALYZER_BATCH_SIZE = 24
ANALYZER_BATCH_WORKERS = max(1, min(4, os.cpu_count() or 1))


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
    """Runs the bundled libclang analyzer and enriches its facts conservatively."""

    def __init__(self, executable: str | Path | None = None) -> None:
        self.executable = Path(executable).expanduser() if executable else None

    def analyze(self, repo: Path, compilation_database: Path, output_dir: Path) -> AnalysisBundle:
        output_dir = output_dir.expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        compiler = self._resolve_executable()
        bundle = AnalysisBundle(mode="partial")
        if compiler is not None:
            try:
                complete = self._run_compiler_analyzer(compiler, repo, compilation_database, output_dir, bundle)
                bundle.mode = "full" if complete else "partial"
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError, AnalysisError) as exc:
                bundle.diagnostics.append(f"libclang analyzer failed; lexical augmentation used: {exc}")
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

    def _run_compiler_analyzer(
        self,
        executable: Path,
        repo: Path,
        compdb: Path,
        output_dir: Path,
        bundle: AnalysisBundle,
    ) -> bool:
        entries = json.loads(compdb.read_text(encoding="utf-8"))
        units = []
        for item in entries:
            source = Path(item["file"])
            source = source if source.is_absolute() else Path(item["directory"]) / source
            if source.exists():
                units.append(str(source.resolve()))
        if not units:
            raise AnalysisError("compile_commands.json 中没有可访问的翻译单元。")
        # Passing every translation-unit path as an argv item exceeds the
        # Windows command-line limit for large repositories.  Keep the list
        # as an explicit UTF-8 artifact and pass only its short path.
        # Keep the temporary list alongside the analysis artifacts.  A run's
        # build directory may be a read-only snapshot (for example when the
        # repository is served from a protected data root), while the output
        # directory is the only location this stage needs to write.
        # libclang's JSON database reader rejects ClangWiki's internal
        # metadata fields (for example ``clangwiki_partial``) even though
        # they are harmless to our own validator.  Feed it a normalized copy
        # and leave the immutable run snapshot untouched.
        analyzer_build_dir = output_dir / ".clangwiki-compdb"
        analyzer_build_dir.mkdir(parents=True, exist_ok=True)
        normalized_entries = []
        for item in entries:
            normalized = {
                key: item[key]
                for key in ("directory", "file", "arguments", "command")
                if key in item
            }
            normalized_entries.append(normalized)
        normalized_compdb = analyzer_build_dir / "compile_commands.json"
        normalized_compdb.write_text(
            json.dumps(normalized_entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        batches = [
            (index, units[start:start + ANALYZER_BATCH_SIZE])
            for index, start in enumerate(range(0, len(units), ANALYZER_BATCH_SIZE))
        ]
        # Probe one batch first so installations built before --sources-file
        # can still use the bounded argv compatibility path below.
        first_index, first_units = batches[0]
        first = self._run_compiler_process(
            executable, repo, analyzer_build_dir, output_dir, first_index, first_units,
        )
        if first[0] != 0 and "usage:" in first[2].lower():
            return self._run_compiler_analyzer_batched(executable, repo, analyzer_build_dir, units, bundle)

        complete = self._collect_compiler_result(bundle, first, first_index)
        if len(batches) == 1:
            return complete

        # Large repositories are intentionally split across a small number of
        # analyzer processes.  libclang is CPU-heavy and a single process can
        # exceed the pipeline timeout before it reaches the later files.
        with ThreadPoolExecutor(max_workers=min(ANALYZER_BATCH_WORKERS, len(batches) - 1)) as pool:
            futures = {
                pool.submit(
                    self._run_compiler_process,
                    executable, repo, analyzer_build_dir, output_dir, index, source_batch,
                ): index
                for index, source_batch in batches[1:]
            }
            results = []
            for future in as_completed(futures):
                results.append((futures[future], future.result()))
        for index, result in sorted(results, key=lambda item: item[0]):
            complete = self._collect_compiler_result(bundle, result, index) and complete
        return complete

    @staticmethod
    def _run_compiler_process(
        executable: Path,
        repo: Path,
        analyzer_build_dir: Path,
        output_dir: Path,
        batch_index: int,
        units: list[str],
    ) -> tuple[int, str, str]:
        source_list = output_dir / f".clangwiki-sources-{batch_index:04d}.txt"
        source_list.write_text("\n".join(units) + "\n", encoding="utf-8")
        command = [
            str(executable), "-p", str(analyzer_build_dir), "--repo-root", str(repo),
            "--sources-file", str(source_list),
        ]
        try:
            process = subprocess.run(
                command, cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=300, check=False,
            )
            return process.returncode, process.stdout, process.stderr
        except (OSError, subprocess.SubprocessError) as exc:
            preview = ", ".join(Path(item).name for item in units[:6])
            suffix = f"; batch sources: {preview}"
            if len(units) > 6:
                suffix += f" (+{len(units) - 6} more)"
            return 1, "", f"{exc}{suffix}"

    def _collect_compiler_result(
        self,
        bundle: AnalysisBundle,
        result: tuple[int, str, str],
        batch_index: int,
    ) -> bool:
        returncode, stdout, stderr = result
        warnings = [line.strip() for line in stderr.splitlines() if line.strip()]
        if returncode != 0:
            detail = " ".join(warnings)[:1200] or f"exit code {returncode}"
            bundle.diagnostics.append(f"libclang batch {batch_index} failed: {detail}")
            return False
        bundle.diagnostics.extend(f"libclang: {line}" for line in warnings)
        self._append_compiler_records(stdout, bundle)
        return not any(
            marker in line.lower()
            for line in warnings
            for marker in ("failed to parse", "no compile command", "cannot enter")
        )

    def _run_compiler_analyzer_batched(
        self,
        executable: Path,
        repo: Path,
        compdb: Path,
        units: list[str],
        bundle: AnalysisBundle,
    ) -> bool:
        """Compatibility path for analyzers built before --sources-file."""
        complete = True
        for start in range(0, len(units), 24):
            process = subprocess.run(
                [str(executable), "-p", str(compdb), "--repo-root", str(repo), *units[start:start + 24]],
                cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=900, check=False,
            )
            if process.returncode != 0:
                raise AnalysisError(process.stderr.strip() or f"exit code {process.returncode}")
            analyzer_warnings = [line.strip() for line in process.stderr.splitlines() if line.strip()]
            bundle.diagnostics.extend(f"libclang: {line}" for line in analyzer_warnings)
            complete = complete and not any(
                marker in line.lower()
                for line in analyzer_warnings
                for marker in ("failed to parse", "no compile command", "cannot enter")
            )
            self._append_compiler_records(process.stdout, bundle)
        return complete

    @staticmethod
    def _append_compiler_records(stdout: str, bundle: AnalysisBundle) -> None:
        for raw in stdout.splitlines():
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
