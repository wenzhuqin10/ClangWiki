from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .errors import CMakeError, CompilationDatabaseError, RepositoryError


def validate_repository(repo: Path) -> Path:
    repo = repo.expanduser().resolve()
    if not repo.is_dir():
        raise RepositoryError(f"代码仓目录不存在：{repo}")
    if not (repo / "CMakeLists.txt").is_file():
        raise RepositoryError(f"未在代码仓根目录发现 CMakeLists.txt：{repo}")
    return repo


def configure_cmake(repo: Path, build_dir: Path) -> Path:
    """Configure only; no build is performed because documentation is read-only."""
    cmake = shutil.which("cmake")
    if cmake is None:
        raise CMakeError("未找到 cmake。请安装 CMake 并将其加入 PATH。")
    build_dir.mkdir(parents=True, exist_ok=True)
    command = [
        cmake, "-S", str(repo), "-B", str(build_dir),
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    ]
    result = subprocess.run(command, cwd=repo, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=False)
    if result.returncode != 0:
        raise CMakeError(
            "CMake 配置失败，ClangWiki 不会修改 CMakeLists.txt。\n"
            f"命令：{' '.join(command)}\n{result.stderr.strip()}"
        )
    return validate_compilation_database(build_dir / "compile_commands.json")


def validate_compilation_database(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise CompilationDatabaseError(f"未生成 compile_commands.json：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompilationDatabaseError(f"编译数据库不是有效 JSON：{path}: {exc}") from exc
    if not isinstance(payload, list) or not payload:
        raise CompilationDatabaseError("编译数据库必须是非空数组。")
    invalid = [item for item in payload if not isinstance(item, dict) or "file" not in item
               or "directory" not in item or ("command" not in item and "arguments" not in item)]
    if invalid:
        raise CompilationDatabaseError("编译数据库中存在缺少 directory/file/command 的条目。")
    return path


def create_fallback_compilation_database(repo: Path, build_dir: Path) -> Path:
    """Create a read-only, best-effort compdb for non-standalone source subtrees.

    This does not claim to reproduce the parent project's build.  It only lets
    the lexical/libclang-compatible analysis path continue with an explicit
    partial-analysis diagnostic when a downloaded subtree cannot be configured
    as an independent CMake project.
    """
    compiler = shutil.which("clang") or shutil.which("clang-cl") or "clang"
    sources = sorted(
        path.resolve()
        for path in repo.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".c", ".cc", ".cpp", ".cxx"}
        and not any(part in {".git", "build", "dist", "third_party", "vendor", "node_modules"}
                    for part in path.relative_to(repo).parts)
    )
    if not sources:
        raise CompilationDatabaseError(f"代码仓中没有可分析的 C/C++ 翻译单元：{repo}")
    build_dir.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "directory": str(repo),
            "file": str(source),
            "arguments": [compiler, "-fsyntax-only", "-I", str(repo), str(source)],
            "clangwiki_partial": True,
        }
        for source in sources
    ]
    target = build_dir / "compile_commands.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return validate_compilation_database(target)


def source_coverage(repo: Path, compilation_database: Path) -> dict[str, object]:
    source_suffixes = {".c", ".cc", ".cpp", ".cxx"}
    excluded = {".git", "build", "dist", "third_party", "vendor", "node_modules"}
    repo_sources = {
        path.resolve() for path in repo.rglob("*")
        if path.is_file() and path.suffix.lower() in source_suffixes
        and not any(part in excluded for part in path.relative_to(repo).parts)
    }
    entries = json.loads(compilation_database.read_text(encoding="utf-8"))
    covered = {_entry_source_path(item).resolve() for item in entries}
    covered_in_repo = repo_sources & covered
    return {
        "repository_source_count": len(repo_sources),
        "compdb_source_count": len(covered),
        "covered_source_count": len(covered_in_repo),
        "uncovered_sources": sorted(str(path.relative_to(repo)).replace("\\", "/")
                                    for path in repo_sources - covered),
    }


def _entry_source_path(item: dict[str, object]) -> Path:
    source = Path(str(item["file"])).expanduser()
    return source if source.is_absolute() else Path(str(item["directory"])) / source
