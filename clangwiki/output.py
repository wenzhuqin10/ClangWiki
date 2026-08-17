from __future__ import annotations

import posixpath
import re
from pathlib import Path

from .document_schema import required_section_headings
from .errors import MarkdownValidationError
from .io import write_text
from .models import DocumentTask, Module


SYNTHESIS_DOCUMENT_TYPES = {
    "subsystem-guide",
    "channel-playbook",
    "repository-guide",
    "architecture",
    # Compatibility with snapshots or direct callers from the previous schema.
    "module-summary",
}

NAVIGATION_SECTION_BY_TYPE = {
    "repository-guide": "快速任务导航",
    "subsystem-guide": "子模块导航",
    "channel-playbook": "功能子模块地图",
    "architecture": "总体模块分层",
    "module-summary": "Agent 开发导航",
}


def validate_markdown(
    markdown: str,
    document_type: str | None = None,
    child_documents: dict[str, str] | None = None,
) -> None:
    value = markdown.strip()
    if len(value) < 40:
        raise MarkdownValidationError("模型输出过短，不能作为有效 Markdown 文档。")
    if not any(line.lstrip().startswith("#") for line in value.splitlines()):
        raise MarkdownValidationError("模型输出缺少 Markdown 标题。")
    lower = value.lower()
    if lower.startswith(("error:", "traceback", "opencode error")):
        raise MarkdownValidationError("模型输出看起来是错误信息，而非文档。")
    if value.count("```") % 2:
        raise MarkdownValidationError("模型输出包含未闭合的代码围栏。")
    if document_type is not None:
        _validate_document_contract(value, document_type)
    if document_type in SYNTHESIS_DOCUMENT_TYPES and child_documents:
        _validate_summary_synthesis(value, child_documents)


def ensure_navigation_card(
    markdown: str,
    task: DocumentTask,
    modules: dict[str, Module],
) -> str:
    """Insert a deterministic first-read card without changing H2 contracts."""
    lines = markdown.rstrip().splitlines()
    title_index = next((index for index, line in enumerate(lines) if line.startswith("# ")), None)
    if title_index is None:
        return markdown
    role = {
        "repository-guide": "仓库导航",
        "architecture": "仓库架构",
        "subsystem-guide": "子系统导航",
        "channel-playbook": "信道任务手册",
        "leaf-engineering": "叶子工程文档",
        "data-structures": "事实参考",
        "call-flows": "事实参考",
        "api-reference": "事实参考",
    }.get(task.document_type, task.document_type)
    module = modules.get(task.module_ids[0]) if len(task.module_ids) == 1 else None
    breadcrumb = _module_breadcrumb(module, modules) if module else "代码仓"
    parent_path = _module_output_path(modules.get(module.parent_id)) if module and module.parent_id else None
    source_scope = ", ".join(f"`{path}`" for path in module.files[:4]) if module else "仓库级综合"
    if module and len(module.files) > 4:
        source_scope += f" 等 {len(module.files)} 个直接文件"
    card = [
        "",
        f"> **导航卡** · 文档角色：{role}  ",
        f"> 当前位置：{breadcrumb}  ",
        f"> 父级文档：{f'`{parent_path}`' if parent_path else '无；这是仓库级入口'}  ",
        f"> 直接子文档：{len(task.child_document_paths)} 个  ",
        f"> 直接源码范围：{source_scope or '无；以子文档综合为主'}",
        "",
    ]
    # Refresh an existing deterministic card when a generated snapshot is
    # re-ingested or repaired instead of stacking duplicate cards.
    if title_index + 2 < len(lines) and lines[title_index + 2].startswith("> **导航卡**"):
        end = title_index + 2
        while end < len(lines) and (lines[end].startswith(">") or not lines[end].strip()):
            end += 1
        lines[title_index + 1:end] = card
    else:
        lines[title_index + 1:title_index + 1] = card
    return "\n".join(lines).rstrip() + "\n"


def ensure_child_document_navigation(
    markdown: str,
    output_relative_path: str,
    child_document_paths: tuple[str, ...],
) -> str:
    """Add deterministic child links without creating another H2 chapter."""
    paths = tuple(dict.fromkeys(path.replace("\\", "/") for path in child_document_paths if path))
    if not paths:
        return markdown
    lines = markdown.rstrip().splitlines()
    heading = f"## {NAVIGATION_SECTION_BY_TYPE.get('module-summary', 'Agent 开发导航')}"
    # New document types place drill-down links in their own navigation-first
    # chapter rather than forcing a shared ninth chapter.
    for document_type, section in NAVIGATION_SECTION_BY_TYPE.items():
        candidate = f"## {section}"
        if candidate in lines:
            heading = candidate
            break
    try:
        start = lines.index(heading)
    except ValueError:
        # The regular schema validator will report the missing required chapter.
        return markdown
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    section = "\n".join(lines[start:end])
    missing = [path for path in paths if path not in section]
    if not missing:
        return markdown
    parent_dir = posixpath.dirname(output_relative_path.replace("\\", "/")) or "."
    navigation = ["", "### 直接子文档"]
    for child_path in missing:
        target = posixpath.relpath(child_path, parent_dir)
        navigation.append(f"- [`{child_path}`]({target})")
    lines[end:end] = navigation
    return "\n".join(lines).rstrip() + "\n"


def _validate_document_contract(markdown: str, document_type: str) -> None:
    expected = required_section_headings(document_type)
    lines = markdown.splitlines()
    actual = tuple(
        line[3:].strip()
        for line in lines
        if line.startswith("## ") and not line.startswith("### ")
    )
    if actual != expected:
        raise MarkdownValidationError(
            f"{document_type} 文档章节不符合契约。期望：{list(expected)}；实际：{list(actual)}"
        )

    positions = [index for index, line in enumerate(lines) if line.startswith("## ")]
    for index, heading in enumerate(expected):
        start = positions[index] + 1
        end = positions[index + 1] if index + 1 < len(positions) else len(lines)
        content = "\n".join(lines[start:end]).strip()
        if not content:
            raise MarkdownValidationError(
                f"章节“{heading}”为空。证据不足时也必须说明无法确认的内容和所需材料。"
            )


def _validate_summary_synthesis(markdown: str, child_documents: dict[str, str]) -> None:
    child_paragraphs = {
        paragraph
        for content in child_documents.values()
        for paragraph in _long_prose_paragraphs(content)
    }
    copied = [paragraph for paragraph in _long_prose_paragraphs(markdown) if paragraph in child_paragraphs]
    if copied:
        raise MarkdownValidationError(
            "导航或层级综合文档包含从直接子文档机械复制的长段落。"
            "请改为父级粒度的跨子模块汇总，并通过子文档链接保留实现细节。"
        )


def _long_prose_paragraphs(markdown: str, minimum_length: int = 240) -> tuple[str, ...]:
    paragraphs: list[str] = []
    current: list[str] = []
    in_fence = False

    def flush() -> None:
        if not current:
            return
        normalised = re.sub(r"\s+", " ", " ".join(current)).strip()
        if len(normalised) >= minimum_length:
            paragraphs.append(normalised)
        current.clear()

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped:
            flush()
            continue
        if stripped.startswith(("#", "- ", "* ", ">", "|", "---")):
            flush()
            continue
        current.append(stripped)
    flush()
    return tuple(paragraphs)


def _module_output_path(module: Module | None) -> str | None:
    if module is None:
        return None
    return f"Modules/{module.source_path or 'root'}/index.md"


def _module_breadcrumb(module: Module, modules: dict[str, Module]) -> str:
    chain: list[str] = []
    current: Module | None = module
    seen: set[str] = set()
    while current is not None and current.module_id not in seen:
        seen.add(current.module_id)
        chain.append(current.display_name)
        current = modules.get(current.parent_id) if current.parent_id else None
    return " → ".join(reversed(chain))


def write_document(output_root: Path, relative_path: str, markdown: str, overwrite: bool) -> Path:
    destination = (output_root / relative_path).resolve()
    if output_root.resolve() not in destination.parents:
        raise MarkdownValidationError("输出路径逃逸到指定 output 目录之外。")
    if destination.exists() and not overwrite:
        raise MarkdownValidationError(f"拒绝覆盖既有文档：{destination}。使用 --overwrite 明确允许覆盖。")
    write_text(destination, markdown.rstrip() + "\n")
    return destination
