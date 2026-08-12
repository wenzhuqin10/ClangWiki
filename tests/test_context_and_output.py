from pathlib import Path

import pytest

from clangwiki.context import build_context
from clangwiki.document_schema import required_section_headings
from clangwiki.models import AnalysisBundle, DocumentTask, Module
from clangwiki.output import validate_markdown


def test_context_marks_uncertain_calls(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.c").write_text("int start(void) { return 0; }\n", encoding="utf-8")
    module = Module(
        "src",
        "src",
        ["src/demo.c"],
        [{"kind": "function", "qualified_name": "start", "file_path": "src/demo.c", "line_start": 1, "line_end": 1, "certainty": "compiler"}],
        source_path="src",
        is_channel_child_leaf=True,
    )
    task = DocumentTask("leaf-module-src", "leaf-module", "src 信道级子模块", "Modules/src/index.md", ("src",), hierarchy_role="leaf")
    result = build_context(
        task,
        tmp_path,
        {"src": module},
        AnalysisBundle(
            "full",
            relations=[
                {
                    "source": "start",
                    "target": "callback",
                    "kind": "POSSIBLE_CALL",
                    "file_path": "src/demo.c",
                    "line": 1,
                    "confidence": 0.5,
                    "certainty": "lexical",
                }
            ],
        ),
        tmp_path / "context.md",
        "简体中文",
        5000,
    )
    context = result.read_text(encoding="utf-8")
    assert "POSSIBLE_CALL" in context
    assert "## 叶子模块概述" in context
    assert "节点类型：信道内叶子模块" in context
    assert "不得改名、遗漏、合并或增加二级章节" in context


def test_context_applies_one_budget_to_symbols_relations_and_source(tmp_path: Path):
    source = tmp_path / "large.c"
    source.write_text("int value;\n" * 4000, encoding="utf-8")
    symbols = [
        {"kind": "function", "qualified_name": f"symbol_{i}", "file_path": "large.c", "line_start": i, "line_end": i}
        for i in range(4000)
    ]
    relations = [
        {"source": f"symbol_{i}", "target": f"symbol_{i + 1}", "kind": "POSSIBLE_CALL", "file_path": "large.c", "line": i}
        for i in range(4000)
    ]
    module = Module("root", "root", ["large.c"], symbols, source_path=".")
    task = DocumentTask("leaf-root", "leaf-module", "root", "Modules/root.md", ("root",), hierarchy_role="leaf")

    path = build_context(task, tmp_path, {"root": module}, AnalysisBundle("partial", relations=relations),
                         tmp_path / "bounded.md", "简体中文", 5000)
    context = path.read_text(encoding="utf-8")

    assert len(context) < 15_000
    assert "符号清单已截断" in context
    assert "关系清单已截断" in context
    assert "上下文预算与截断统计" in context


def test_markdown_validation_requires_heading():
    validate_markdown("# 标题\n\n" + "正文内容。" * 20)
    with pytest.raises(Exception):
        validate_markdown("正文内容。" * 20)


def test_markdown_validation_enforces_document_contract():
    sections = required_section_headings("leaf-module")
    markdown = ["# 示例模块"]
    for heading in sections:
        markdown.extend(["", f"## {heading}", "当前证据无法确定；需要补充运行日志或设计文档。"])
    validate_markdown("\n".join(markdown), "leaf-module")

    with pytest.raises(Exception):
        validate_markdown("# 示例模块\n\n## 叶子模块概述\n内容足够长但章节不完整。" * 4, "leaf-module")
