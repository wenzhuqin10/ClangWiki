from pathlib import Path

import pytest

from clangwiki.errors import OpenCodeError
from clangwiki.opencode import OpenCodeRunner
from clangwiki.rag import RagService


def test_opencode_command_is_cli_only(tmp_path: Path):
    runner = OpenCodeRunner("nga", "company/glm-5.1", "clangwiki-doc", 900)
    command = runner.command(tmp_path / "task.md")
    assert command[1] == "run"
    assert command[2].startswith("Read the ClangWiki task context")
    assert command[3:5] == ["--model", "company/glm-5.1"]
    assert "--file" not in command
    assert command[-2:] == ["--agent", "clangwiki-doc"]
    assert "serve" not in command


def test_rag_model_failure_keeps_actionable_diagnostic(tmp_path: Path):
    class FailingRunner:
        def run_prompt(self, *_args):
            raise OpenCodeError("退出码 1；stderr 日志：tmp/rag/stderr.log；模型未找到")

    with pytest.raises(OpenCodeError, match="RAG 初次回答生成失败.*模型未找到"):
        RagService._run_model(
            FailingRunner(), tmp_path, tmp_path / "context.md", tmp_path / "out.log", tmp_path / "err.log", "回答", "初次回答生成",
        )
