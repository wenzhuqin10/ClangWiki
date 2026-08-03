from __future__ import annotations

from pathlib import Path

from .document_schema import required_section_headings
from .errors import MarkdownValidationError
from .io import write_text


def validate_markdown(markdown: str, document_type: str | None = None) -> None:
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


def write_document(output_root: Path, relative_path: str, markdown: str, overwrite: bool) -> Path:
    destination = (output_root / relative_path).resolve()
    if output_root.resolve() not in destination.parents:
        raise MarkdownValidationError("输出路径逃逸到指定 output 目录之外。")
    if destination.exists() and not overwrite:
        raise MarkdownValidationError(f"拒绝覆盖既有文档：{destination}。使用 --overwrite 明确允许覆盖。")
    write_text(destination, markdown.rstrip() + "\n")
    return destination
