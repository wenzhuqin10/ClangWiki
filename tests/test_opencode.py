from pathlib import Path

from clangwiki.opencode import OpenCodeRunner


def test_opencode_command_is_cli_only(tmp_path: Path):
    runner = OpenCodeRunner("nga", "company/glm-5.1", "clangwiki-doc", 900)
    command = runner.command(tmp_path / "task.md")
    assert command[1:5] == ["run", "--model", "company/glm-5.1", "--file"]
    assert "--agent" in command
    assert "serve" not in command

