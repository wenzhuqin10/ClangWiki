from pathlib import Path

import pytest

from clangwiki.context import build_context
from clangwiki.models import AnalysisBundle, DocumentTask, Module
from clangwiki.output import validate_markdown


def test_context_marks_uncertain_calls(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "demo.c").write_text("int start(void) { return 0; }\n", encoding="utf-8")
    module = Module("src", "src", ["src/demo.c"], [{"kind": "function", "qualified_name": "start", "file_path": "src/demo.c", "line_start": 1, "line_end": 1, "certainty": "compiler"}])
    task = DocumentTask("module-src", "module", "src 模块", "Modules/src.md", ("src",))
    result = build_context(task, tmp_path, {"src": module}, AnalysisBundle("full", relations=[{"source": "start", "target": "callback", "kind": "POSSIBLE_CALL", "file_path": "src/demo.c", "line": 1, "confidence": 0.5, "certainty": "lexical"}]), tmp_path / "context.md", "简体中文", 5000)
    assert "POSSIBLE_CALL" in result.read_text(encoding="utf-8")


def test_markdown_validation_requires_heading():
    validate_markdown("# 标题\n\n" + "正文内容。" * 20)
    with pytest.raises(Exception):
        validate_markdown("正文内容。" * 20)

