from pathlib import Path

import pytest

from clangwiki.context import build_context
from clangwiki.document_schema import required_section_headings
from clangwiki.models import AnalysisBundle, DocumentTask, Module
from clangwiki.output import (
    ensure_child_document_navigation,
    ensure_navigation_card,
    select_final_complete_document,
    validate_markdown,
)


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
    task = DocumentTask("leaf-engineering-src", "leaf-engineering", "src 叶子工程文档", "Modules/src/index.md", ("src",), hierarchy_role="leaf")
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
    assert "## 功能目标与责任边界" in context
    assert "节点类型：信道内叶子工程单元" in context
    assert "不得改名、遗漏、合并或增加二级章节" in context
    assert "当前文档是进入源码前的最深工程知识单元" in context


def test_summary_context_uses_child_documents_as_primary_evidence(tmp_path: Path):
    output = tmp_path / "output"
    child_relative = "Modules/pdsch/encoder/index.md"
    child_path = output / child_relative
    child_path.parent.mkdir(parents=True)
    child_path.write_text("# Encoder\n\n## 模块概述\n编码子模块事实。\n", encoding="utf-8")
    parent = Module(
        "pdsch", "PDSCH", [], [], source_path="pdsch", child_ids=("encoder",), is_leaf=False, is_channel_root=True,
    )
    child = Module(
        "encoder", "Encoder", [], [], source_path="pdsch/encoder", parent_id="pdsch", is_leaf=True,
    )
    task = DocumentTask(
        "channel-playbook-pdsch", "channel-playbook", "PDSCH 信道任务手册", "Modules/pdsch/index.md",
        ("pdsch",), hierarchy_role="channel", child_document_paths=(child_relative,),
    )

    path = build_context(
        task, tmp_path, {"pdsch": parent, "encoder": child}, AnalysisBundle("full"),
        tmp_path / "summary-context.md", "简体中文", 5000, output,
    )
    context = path.read_text(encoding="utf-8")

    assert "当前文档恢复一个信道的端到端业务" in context
    assert "局部实现留在叶子工程文档" in context
    assert "以下直接子文档是主要证据" in context
    assert child_relative in context


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
    task = DocumentTask("leaf-root", "leaf-engineering", "root", "Modules/root.md", ("root",), hierarchy_role="leaf")

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
    sections = required_section_headings("leaf-engineering")
    assert sections == (
        "功能目标与责任边界", "领域原理与实现约束", "源码地图", "执行流程与调用链",
        "数据结构与字段语义", "配置、宏与运行模式", "状态、时序与资源生命周期",
        "异常路径与故障定位", "修改指南与影响分析", "测试与验证", "相关文档与证据限制",
    )
    markdown = ["# 示例模块"]
    for heading in sections:
        markdown.extend(["", f"## {heading}", "当前证据无法确定；需要补充运行日志或设计文档。"])
    validate_markdown("\n".join(markdown), "leaf-engineering")

    with pytest.raises(Exception):
        validate_markdown("# 示例模块\n\n## 功能目标与责任边界\n内容足够长但章节不完整。" * 4, "leaf-engineering")


def test_selects_last_complete_document_from_progressive_opencode_output():
    sections = required_section_headings("leaf-engineering")

    def document(label: str, count: int) -> str:
        lines = [f"# {label}"]
        for heading in sections[:count]:
            lines.extend(["", f"## {heading}", f"{label} 的 {heading} 内容。"])
        return "\n".join(lines)

    raw = "\n".join([
        document("第一次未完成", 3),
        document("第二次完整", len(sections)),
        document("最后一次完整", len(sections)),
    ])
    selected = select_final_complete_document(raw, "leaf-engineering")

    assert selected.startswith("# 最后一次完整")
    assert "# 第一次未完成" not in selected
    assert selected.count("\n## ") == len(sections)
    validate_markdown(selected, "leaf-engineering")


def test_keeps_original_output_when_no_complete_document_exists():
    raw = "# 第一次\n\n## 功能目标与责任边界\n内容\n# 第二次\n\n## 功能目标与责任边界\n内容"

    assert select_final_complete_document(raw, "leaf-engineering") == raw


def test_summary_navigation_is_added_without_new_second_level_chapter():
    markdown = _valid_summary_markdown()
    result = ensure_child_document_navigation(
        markdown,
        "Modules/pdsch/index.md",
        ("Modules/pdsch/encoder/index.md", "Modules/pdsch/mapping/index.md"),
    )

    assert "### 直接子文档" in result
    assert "[`Modules/pdsch/encoder/index.md`](encoder/index.md)" in result
    assert "[`Modules/pdsch/mapping/index.md`](mapping/index.md)" in result
    validate_markdown(result, "channel-playbook")


def test_summary_validation_rejects_mechanical_child_copy():
    copied = "父级文档不应直接复制这一段子模块实现说明。" * 24
    markdown = _valid_summary_markdown({"信道定位与处理目标": copied})
    child = f"# Encoder\n\n## 核心实现\n\n{copied}\n"

    with pytest.raises(Exception, match="机械复制"):
        validate_markdown(
            markdown,
            "channel-playbook",
            {"Modules/pdsch/encoder/index.md": child},
        )


def _valid_summary_markdown(overrides: dict[str, str] | None = None) -> str:
    values = overrides or {}
    lines = ["# PDSCH 信道任务手册"]
    for heading in required_section_headings("channel-playbook"):
        lines.extend([
            "",
            f"## {heading}",
            values.get(heading, "当前证据无法确定；需要继续下钻直接子文档和源码证据。"),
        ])
    return "\n".join(lines)


def test_navigation_card_is_deterministic_and_keeps_section_contract():
    module = Module("encoder", "Encoder", ["pdsch/encoder.c"], [], source_path="pdsch/encoder")
    task = DocumentTask(
        "leaf-engineering-encoder", "leaf-engineering", "Encoder", "Modules/pdsch/encoder/index.md",
        ("encoder",), hierarchy_role="leaf",
    )
    markdown = ["# Encoder"]
    for heading in required_section_headings("leaf-engineering"):
        markdown.extend(["", f"## {heading}", "当前证据无法确定；需要补充运行时证据。"])
    result = ensure_navigation_card("\n".join(markdown), task, {"encoder": module})

    assert "**导航卡** · 文档角色：叶子工程文档" in result
    assert "当前位置：Encoder" in result
    assert "`pdsch/encoder.c`" in result
    validate_markdown(result, "leaf-engineering")
