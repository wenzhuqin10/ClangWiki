from pathlib import Path

from clangwiki.opencode import OpenCodeRunner


def test_opencode_command_is_cli_only(tmp_path: Path):
    runner = OpenCodeRunner("nga", "company/glm-5.1", "clangwiki-doc", 900)
    command = runner.command(tmp_path / "task.md")
    assert command[1] == "run"
    assert command[2].startswith("Read the ClangWiki task context")
    assert command[3:5] == ["--model", "company/glm-5.1"]
    assert "--file" not in command
    assert command[-2:] == ["--agent", "clangwiki-doc"]
    assert "serve" not in command
