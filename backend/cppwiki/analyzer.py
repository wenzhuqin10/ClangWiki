import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
EXCLUDED_DIRS = {".git", ".cppwiki", "build", "dist", "node_modules", "vendor", "third_party"}
FUNC_RE = re.compile(
    r"(?m)^[ \t]*(?:template\s*<[^;{]+>\s*)?(?P<prefix>(?:[\w:<>,*&~]+\s+)+)"
    r"(?P<name>(?:\w+::)*~?\w+)\s*\((?P<args>[^;{}]*)\)\s*(?:const\s*)?(?:override\s*)?\{"
)
TYPE_RE = re.compile(
    r"(?m)^[ \t]*(?:template\s*<[^;{]+>\s*)?(?P<kind>class|struct|enum)\s+"
    r"(?P<name>\w+)(?:\s+final)?(?:\s*:\s*(?P<bases>[^\{]+))?\s*\{"
)
INCLUDE_RE = re.compile(r"(?m)^\s*#\s*include\s*[<\"]([^>\"]+)[>\"]")
MACRO_RE = re.compile(r"(?m)^\s*#\s*define\s+(\w+)(?:\([^\n]*?\))?\s*(.*)$")
CALL_RE = re.compile(r"\b([A-Za-z_]\w*(?:::\w+)*)\s*\(")
CALL_KEYWORDS = {"if", "for", "while", "switch", "return", "sizeof", "alignof", "catch"}


@dataclass
class AnalysisResult:
    mode: str
    confidence: float
    symbols: List[Dict[str, Any]] = field(default_factory=list)
    relations: List[Dict[str, Any]] = field(default_factory=list)
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def repository_id(root: Path) -> str:
    normalized = str(root.resolve()).replace("\\", "/").lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def source_files(root: Path) -> List[Path]:
    result = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts):
            continue
        result.append(path)
    return sorted(result)


def _brace_end(text: str, opening: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    quote = ""
    for index in range(opening, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                in_string = False
            continue
        if char in ('"', "'"):
            in_string = True
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _stable_id(*parts: object) -> str:
    return hashlib.sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()


class RepositoryAnalyzer:
    def __init__(self, analyzer_path: Path):
        self.analyzer_path = Path(analyzer_path)

    def analyze(
        self, root: Path, compile_database: Optional[Path] = None
    ) -> AnalysisResult:
        root = root.resolve()
        files = source_files(root)
        if not files:
            return AnalysisResult("fallback", 0.35, errors=["No C/C++ source files found"])

        compile_db = self._find_compile_database(root, compile_database)
        tool = self._resolve_tool()
        if compile_db and tool:
            try:
                result = self._run_compiler(tool, root, compile_db, files)
                self._augment_lexical(root, files, result, only_missing=True)
                self._build_chunks(root, result)
                return result
            except Exception as exc:
                fallback = AnalysisResult(
                    "partial", 0.65, errors=["Compiler analyzer failed: %s" % exc]
                )
                self._augment_lexical(root, files, fallback)
                self._build_chunks(root, fallback)
                return fallback

        mode = "partial" if shutil.which("clang") else "fallback"
        confidence = 0.55 if mode == "partial" else 0.35
        errors = []
        if not compile_db:
            errors.append("compile_commands.json not found; semantic resolution is limited")
        if not tool:
            errors.append("cpp-analyzer not built; using lexical fallback")
        result = AnalysisResult(mode, confidence, errors=errors)
        self._augment_lexical(root, files, result)
        self._build_chunks(root, result)
        return result

    def _resolve_tool(self) -> Optional[Path]:
        if self.analyzer_path.is_file():
            return self.analyzer_path.resolve()
        found = shutil.which("cpp-analyzer")
        return Path(found) if found else None

    @staticmethod
    def _find_compile_database(root: Path, explicit: Optional[Path]) -> Optional[Path]:
        candidates = []
        if explicit:
            candidates.append(explicit / "compile_commands.json" if explicit.is_dir() else explicit)
        candidates.extend([root / "compile_commands.json", root / "build" / "compile_commands.json"])
        return next((path.resolve() for path in candidates if path.is_file()), None)

    def _run_compiler(
        self, tool: Path, root: Path, compile_db: Path, files: Sequence[Path]
    ) -> AnalysisResult:
        commands = json.loads(compile_db.read_text(encoding="utf-8"))
        translation_units = [Path(item["file"]).resolve() for item in commands]
        translation_units = [path for path in translation_units if path.exists()]
        if not translation_units:
            raise RuntimeError("Compilation database contains no existing translation units")
        process = subprocess.run(
            [str(tool), "-p", str(compile_db.parent), "--repo-root", str(root)]
            + [str(path) for path in translation_units],
            cwd=str(root), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=900, check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(process.stderr.strip() or "exit code %d" % process.returncode)
        result = AnalysisResult("full", 0.95)
        for raw in process.stdout.splitlines():
            if not raw.strip():
                continue
            item = json.loads(raw)
            if item.get("record") == "symbol":
                result.symbols.append(item)
            elif item.get("record") == "relation":
                result.relations.append(item)
        return result

    def _augment_lexical(
        self,
        root: Path,
        files: Sequence[Path],
        result: AnalysisResult,
        only_missing: bool = False,
    ) -> None:
        existing = {
            (row.get("qualified_name"), row.get("file_path"), row.get("line_start"))
            for row in result.symbols
        }
        defined_names = set(row.get("name") for row in result.symbols)
        function_bodies: List[Tuple[str, str, int, str]] = []
        for path in files:
            relative = path.relative_to(root).as_posix()
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                result.errors.append("%s: %s" % (relative, exc))
                continue

            for include in INCLUDE_RE.finditer(text):
                result.relations.append({
                    "source": relative, "target": include.group(1), "kind": "INCLUDES",
                    "file_path": relative, "line": _line(text, include.start()), "confidence": 1.0,
                })
            for macro in MACRO_RE.finditer(text):
                name = macro.group(1)
                key = (name, relative, _line(text, macro.start()))
                if not only_missing or key not in existing:
                    result.symbols.append({
                        "kind": "macro", "name": name, "qualified_name": name,
                        "file_path": relative, "line_start": key[2], "line_end": key[2],
                        "signature": macro.group(0).strip(),
                    })

            for match in TYPE_RE.finditer(text):
                name = match.group("name")
                end = _brace_end(text, text.find("{", match.start(), match.end()))
                start_line, end_line = _line(text, match.start()), _line(text, end)
                key = (name, relative, start_line)
                if not only_missing or key not in existing:
                    result.symbols.append({
                        "kind": match.group("kind"), "name": name, "qualified_name": name,
                        "file_path": relative, "line_start": start_line, "line_end": end_line,
                        "signature": match.group(0).split("{")[0].strip(),
                    })
                bases = match.group("bases") or ""
                for base in re.findall(r"(?:public|protected|private|virtual|\s)*([A-Za-z_]\w*(?:::\w+)*)", bases):
                    result.relations.append({
                        "source": name, "target": base, "kind": "INHERITS",
                        "file_path": relative, "line": start_line, "confidence": 0.9,
                    })

            for match in FUNC_RE.finditer(text):
                name = match.group("name")
                opening = text.find("{", match.start(), match.end())
                end = _brace_end(text, opening)
                start_line, end_line = _line(text, match.start()), _line(text, end)
                key = (name, relative, start_line)
                if not only_missing or key not in existing:
                    result.symbols.append({
                        "kind": "function", "name": name.split("::")[-1],
                        "qualified_name": name, "file_path": relative,
                        "line_start": start_line, "line_end": end_line,
                        "signature": text[match.start():opening].strip(),
                    })
                defined_names.add(name)
                function_bodies.append((name, relative, start_line, text[opening + 1:end - 1]))

        simple_to_qualified = {}
        for row in result.symbols:
            if row.get("kind") in ("function", "method"):
                simple_to_qualified.setdefault(row["name"], []).append(row["qualified_name"])
        for caller, relative, line_number, body in function_bodies:
            for call in CALL_RE.finditer(body):
                raw = call.group(1)
                simple = raw.split("::")[-1]
                if simple in CALL_KEYWORDS or simple == caller.split("::")[-1]:
                    continue
                candidates = simple_to_qualified.get(simple, [])
                if len(candidates) == 1:
                    target, kind, confidence = candidates[0], "CALLS", 0.8
                else:
                    target, kind, confidence = raw, "POSSIBLE_CALL", 0.45
                result.relations.append({
                    "source": caller, "target": target, "kind": kind,
                    "file_path": relative, "line": line_number + body.count("\n", 0, call.start()),
                    "confidence": confidence,
                })

        result.symbols = _deduplicate(result.symbols, ("qualified_name", "file_path", "line_start"))
        result.relations = _deduplicate(
            result.relations, ("source", "target", "kind", "file_path", "line")
        )

    @staticmethod
    def _build_chunks(root: Path, result: AnalysisResult) -> None:
        for symbol in result.symbols:
            path = root / symbol["file_path"]
            if not path.is_file():
                continue
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            start = max(1, int(symbol["line_start"]))
            end = min(len(lines), max(start, int(symbol["line_end"])))
            content = "\n".join(lines[start - 1:end])
            if not content.strip():
                continue
            result.chunks.append({
                "id": _stable_id(symbol["file_path"], start, end, symbol["qualified_name"]),
                "symbol_key": (symbol["qualified_name"], symbol["file_path"], start),
                "symbol": symbol["qualified_name"], "kind": symbol["kind"],
                "file_path": symbol["file_path"], "line_start": start, "line_end": end,
                "content": "Symbol: %s\nKind: %s\nFile: %s:%d-%d\n%s" % (
                    symbol["qualified_name"], symbol["kind"], symbol["file_path"], start, end, content
                ),
            })


def _deduplicate(rows: Iterable[Dict[str, Any]], keys: Sequence[str]) -> List[Dict[str, Any]]:
    result = []
    seen = set()
    for row in rows:
        key = tuple(row.get(field) for field in keys)
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result
