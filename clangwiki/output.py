from __future__ import annotations

import posixpath
import re
from pathlib import Path

from .document_schema import required_section_headings
from .errors import MarkdownValidationError
from .io import write_text


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
    if document_type == "module-summary" and child_documents:
        _validate_summary_synthesis(value, child_documents)


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
    heading = "## Agent 开发导航"
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
            "module-summary 文档包含从直接子文档机械复制的长段落。"
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


def write_document(output_root: Path, relative_path: str, markdown: str, overwrite: bool) -> Path:
    destination = (output_root / relative_path).resolve()
    if output_root.resolve() not in destination.parents:
        raise MarkdownValidationError("输出路径逃逸到指定 output 目录之外。")
    if destination.exists() and not overwrite:
        raise MarkdownValidationError(f"拒绝覆盖既有文档：{destination}。使用 --overwrite 明确允许覆盖。")
    write_text(destination, markdown.rstrip() + "\n")
    return destination
