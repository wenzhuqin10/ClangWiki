from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .errors import ClangWikiError


DEFAULT_MODULE_GENERATION_CONCURRENCY = 2
MIN_MODULE_GENERATION_CONCURRENCY = 1
MAX_MODULE_GENERATION_CONCURRENCY = 4
MODULE_GENERATION_CONCURRENCY_ERROR = "模块生成并发数必须是 1 到 4 之间的整数。"


def normalize_module_generation_concurrency(value: Any) -> int:
    """Return one validated fan-out value for every configuration entry point.

    The setting controls only independent leaf-engineering ``opencode run`` calls.
    Keeping the validation here prevents the CLI, HTTP API, persisted config and
    direct ``RunConfig`` users from silently applying different rules.
    """
    if value is None or value == "":
        return DEFAULT_MODULE_GENERATION_CONCURRENCY
    if isinstance(value, bool):
        raise ClangWikiError(MODULE_GENERATION_CONCURRENCY_ERROR)
    if isinstance(value, float) and not value.is_integer():
        raise ClangWikiError(MODULE_GENERATION_CONCURRENCY_ERROR)
    try:
        concurrency = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ClangWikiError(MODULE_GENERATION_CONCURRENCY_ERROR) from exc
    if not MIN_MODULE_GENERATION_CONCURRENCY <= concurrency <= MAX_MODULE_GENERATION_CONCURRENCY:
        raise ClangWikiError(MODULE_GENERATION_CONCURRENCY_ERROR)
    return concurrency


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

    def __post_init__(self) -> None:
        # RunConfig is also used by the legacy one-shot CLI, so it must enforce
        # the same bounds as the persisted repository configuration.
        object.__setattr__(
            self,
            "module_generation_concurrency",
            normalize_module_generation_concurrency(self.module_generation_concurrency),
        )


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
