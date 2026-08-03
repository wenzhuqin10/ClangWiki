from __future__ import annotations

from collections import defaultdict
from pathlib import Path, PurePosixPath

from .build import source_coverage
from .errors import ModuleConfigurationError
from .io import write_json
from .models import AnalysisBundle, Module


# Used only when the caller does not provide explicit --leaf-module-path values.
# Explicit repository paths always take precedence over this domain heuristic.
BASEBAND_CHANNEL_NAMES = frozenset(
    {
        "pdsch",
        "pusch",
        "pdcch",
        "pucch",
        "pbch",
        "prach",
        "ssb",
        "csirs",
        "srs",
    }
)


def build_knowledge(
    repo: Path,
    compilation_database: Path,
    analysis: AnalysisBundle,
    output_dir: Path,
    leaf_module_paths: tuple[str, ...] = (),
) -> dict[str, Module]:
    """Build a directory-backed hierarchy whose leaves stop at channel boundaries.

    Source files below a configured channel path remain part of that channel leaf instead of
    becoming smaller documents. Files outside configured leaves are assigned to their first
    repository directory and become direct evidence of the corresponding parent module.
    """

    source_files = sorted({_normalise_path(str(row["path"])) for row in analysis.files})
    configured_leaves = _resolve_leaf_paths(source_files, leaf_module_paths)
    if leaf_module_paths:
        _validate_explicit_leaf_paths(source_files, configured_leaves)
    owner_by_file = {path: _owner_path(path, configured_leaves) for path in source_files}

    direct_files_by_path: dict[str, list[str]] = defaultdict(list)
    for path, owner in owner_by_file.items():
        direct_files_by_path[owner].append(path)

    module_paths: set[str] = set()
    for owner in direct_files_by_path:
        module_paths.update(_ancestors(owner))

    id_by_path = {path: _module_id(path) for path in sorted(module_paths)}
    children_by_path: dict[str, list[str]] = defaultdict(list)
    for path in module_paths:
        parent = _parent_path(path)
        if parent is not None and parent in module_paths:
            children_by_path[parent].append(path)

    symbols_by_path: dict[str, list[dict[str, object]]] = defaultdict(list)
    for symbol in analysis.symbols:
        file_path = _normalise_path(str(symbol.get("file_path", "")))
        owner = owner_by_file.get(file_path)
        if owner is not None:
            symbols_by_path[owner].append(symbol)

    modules: dict[str, Module] = {}
    for path in sorted(module_paths, key=lambda value: (_depth(value), value)):
        module_id = id_by_path[path]
        parent_path = _parent_path(path)
        children = tuple(id_by_path[child] for child in sorted(children_by_path[path]))
        modules[module_id] = Module(
            module_id=module_id,
            display_name="代码仓" if path == "root" else PurePosixPath(path).name,
            files=sorted(direct_files_by_path[path]),
            symbols=symbols_by_path[path],
            source_path="" if path == "root" else path,
            parent_id=id_by_path[parent_path] if parent_path in id_by_path else None,
            child_ids=children,
            depth=_depth(path),
            is_leaf=not children,
            is_channel_leaf=path in configured_leaves,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "repository.json",
        {
            "root": str(repo),
            "analysis_mode": analysis.mode,
            "diagnostics": analysis.diagnostics,
            "leaf_module_paths": sorted(configured_leaves),
            "leaf_strategy": "explicit" if leaf_module_paths else "baseband-channel-auto-or-top-level",
        },
    )
    write_json(
        output_dir / "modules.json",
        [
            {
                "module_id": module.module_id,
                "display_name": module.display_name,
                "source_path": module.source_path,
                "parent_id": module.parent_id,
                "child_ids": list(module.child_ids),
                "depth": module.depth,
                "is_leaf": module.is_leaf,
                "is_channel_leaf": module.is_channel_leaf,
                "direct_files": module.files,
                "symbol_count": len(module.symbols),
            }
            for module in modules.values()
        ],
    )
    write_json(
        output_dir / "module_tree.json",
        {
            "roots": [module.module_id for module in modules.values() if module.parent_id is None],
            "nodes": {
                module.module_id: {
                    "display_name": module.display_name,
                    "source_path": module.source_path,
                    "parent_id": module.parent_id,
                    "child_ids": list(module.child_ids),
                    "depth": module.depth,
                    "is_leaf": module.is_leaf,
                    "is_channel_leaf": module.is_channel_leaf,
                }
                for module in modules.values()
            },
        },
    )
    write_json(output_dir / "symbols.json", analysis.symbols)
    write_json(output_dir / "relations.json", analysis.relations)
    write_json(output_dir / "source_coverage.json", source_coverage(repo, compilation_database))
    return modules


def _resolve_leaf_paths(files: list[str], configured: tuple[str, ...]) -> set[str]:
    if configured:
        leaves = {_normalise_path(path).strip("/") for path in configured}
        return {path for path in leaves if path and path != "."}

    detected: set[str] = set()
    for file_path in files:
        directories = list(PurePosixPath(file_path).parts[:-1])
        for index, part in enumerate(directories):
            if _normalise_channel_name(part) in BASEBAND_CHANNEL_NAMES:
                detected.add("/".join(directories[: index + 1]))
                break
    if detected:
        return detected

    return {_fallback_owner(path) for path in files}


def _validate_explicit_leaf_paths(files: list[str], leaves: set[str]) -> None:
    unmatched = sorted(
        leaf for leaf in leaves if not any(path.startswith(f"{leaf}/") or path == leaf for path in files)
    )
    if unmatched:
        raise ModuleConfigurationError(
            "以下 --leaf-module-path 未覆盖任何已分析源码文件："
            + ", ".join(unmatched)
            + "。路径必须相对于代码仓根目录，并使用源码目录而不是输出目录。"
        )

    overlapping = sorted(
        (parent, child)
        for parent in leaves
        for child in leaves
        if parent != child and child.startswith(f"{parent}/")
    )
    if overlapping:
        pairs = ", ".join(f"{parent} -> {child}" for parent, child in overlapping)
        raise ModuleConfigurationError(
            "叶子模块路径不能互为祖先和后代，否则最小文档边界不明确：" + pairs
        )


def _owner_path(file_path: str, leaves: set[str]) -> str:
    matches = [leaf for leaf in leaves if file_path == leaf or file_path.startswith(f"{leaf}/")]
    if matches:
        return max(matches, key=lambda value: len(PurePosixPath(value).parts))

    shared_parents = {
        ancestor
        for leaf in leaves
        for ancestor in _ancestors(leaf)[:-1]
        if file_path.startswith(f"{ancestor}/")
    }
    if shared_parents:
        return max(shared_parents, key=lambda value: len(PurePosixPath(value).parts))
    return _fallback_owner(file_path)


def _fallback_owner(file_path: str) -> str:
    parts = PurePosixPath(file_path).parts
    return parts[0] if len(parts) > 1 else "root"


def _ancestors(path: str) -> tuple[str, ...]:
    if path == "root":
        return ("root",)
    parts = PurePosixPath(path).parts
    return tuple("/".join(parts[:index]) for index in range(1, len(parts) + 1))


def _parent_path(path: str) -> str | None:
    if path == "root":
        return None
    parts = PurePosixPath(path).parts
    if len(parts) == 1:
        return None
    return "/".join(parts[:-1])


def _depth(path: str) -> int:
    return 0 if path == "root" else len(PurePosixPath(path).parts) - 1


def _normalise_path(value: str) -> str:
    return value.replace("\\", "/").strip("/")


def _normalise_channel_name(value: str) -> str:
    return value.lower().replace("-", "").replace("_", "")


def _module_id(path: str) -> str:
    if path == "root":
        return "root"
    value = path.replace("/", "--")
    return "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value).strip("-") or "root"
