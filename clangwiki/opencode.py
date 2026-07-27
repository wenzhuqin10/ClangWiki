from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .errors import OpenCodeError
from .io import write_text


class OpenCodeRunner:
    """Thin CLI adapter. It never accesses credentials or starts an HTTP service."""

    def __init__(self, executable: str, model: str, agent: str | None, timeout_seconds: int) -> None:
        self.executable = executable
        self.model = model
        self.agent = agent
        self.timeout_seconds = timeout_seconds

    def command(self, context_file: Path) -> list[str]:
        executable = shutil.which(self.executable) or self.executable
        command = [executable, "run", "--model", self.model, "--file", str(context_file)]
        if self.agent:
            command.extend(["--agent", self.agent])
        command.append("依据附件的 ClangWiki 任务上下文生成文档。仅输出最终 Markdown 正文。")
        return command

    def generate(self, repository: Path, context_file: Path, stdout_log: Path, stderr_log: Path) -> str:
        if shutil.which(self.executable) is None and not Path(self.executable).is_file():
            raise OpenCodeError(
                f"未找到 OpenCode 可执行文件 '{self.executable}'。请安装 OpenCode，或使用 --opencode-executable 指向企业兼容启动器。"
            )
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            result = subprocess.run(self.command(context_file), cwd=repository, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=self.timeout_seconds,
                creationflags=flags, check=False)
        except subprocess.TimeoutExpired as exc:
            raise OpenCodeError(f"opencode run 在 {self.timeout_seconds} 秒内未完成。") from exc
        write_text(stdout_log, result.stdout)
        write_text(stderr_log, result.stderr)
        if result.returncode != 0:
            raise OpenCodeError(f"opencode run 失败（退出码 {result.returncode}）。详见：{stderr_log}")
        output = result.stdout.strip()
        if not output:
            raise OpenCodeError(f"opencode run 返回空输出。详见：{stderr_log}")
        return output

