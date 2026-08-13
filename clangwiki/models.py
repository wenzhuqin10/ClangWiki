from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunConfig:
    repo: Path
    workspace: Path
    output: Path
    build_dir: Path
    model: str
    opencode_executable: str = "opencode"
    agent: str | None = "clangwiki-doc"
    timeout_seconds: int = 900
    language: str = "简体中文"
    max_source_chars_per_task: int = 36000
    module_generation_concurrency: int = 2
    overwrite: bool = False
    skip_cmake: bool = False
    skip_analysis: bool = False
    only: tuple[str, ...] = ()
    module_ids: tuple[str, ...] = ()
    leaf_module_paths: tuple[str, ...] = ()
    channel_module_paths: tuple[str, ...] = ()


@dataclass
class AnalysisBundle:
    mode: str
    diagnostics: list[str] = field(default_factory=list)
    files: list[dict[str, Any]] = field(default_factory=list)
    symbols: list[dict[str, Any]] = field(default_factory=list)
    relations: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DocumentTask:
    task_id: str
    document_type: str
    title: str
    output_relative_path: str
    module_ids: tuple[str, ...]
    hierarchy_role: str = "repository"
    child_document_paths: tuple[str, ...] = ()


@dataclass
class Module:
    module_id: str
    display_name: str
    files: list[str]
    symbols: list[dict[str, Any]]
    source_path: str = ""
    parent_id: str | None = None
    child_ids: tuple[str, ...] = ()
    depth: int = 0
    is_leaf: bool = True
    is_channel_root: bool = False
    is_channel_child_leaf: bool = False
