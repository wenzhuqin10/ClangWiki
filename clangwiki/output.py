from __future__ import annotations

from pathlib import Path

from .errors import MarkdownValidationError
from .io import write_text


def validate_markdown(markdown: str) -> None:
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


def write_document(output_root: Path, relative_path: str, markdown: str, overwrite: bool) -> Path:
    destination = (output_root / relative_path).resolve()
    if output_root.resolve() not in destination.parents:
        raise MarkdownValidationError("输出路径逃逸到指定 output 目录之外。")
    if destination.exists() and not overwrite:
        raise MarkdownValidationError(f"拒绝覆盖既有文档：{destination}。使用 --overwrite 明确允许覆盖。")
    write_text(destination, markdown.rstrip() + "\n")
    return destination

