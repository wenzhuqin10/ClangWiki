from __future__ import annotations

import json
import os
import re
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

    def command(self, context_file: Path, prompt: str | None = None) -> list[str]:
        executable = shutil.which(self.executable) or self.executable
        message = prompt or (
            "Read the ClangWiki task context from standard input and generate the requested document. "
            "严格遵守其中的章节契约和证据分级，"
            "不得改名、遗漏、合并或增加二级章节；证据不足时保留章节并明确说明。"
            "仅输出最终 Markdown 正文。"
        )
        command = [executable, "run", message, "--model", self.model]
        command.extend(["--agent", self.agent or "clangwiki-doc"])
        return command

    def generate(self, repository: Path, context_file: Path, stdout_log: Path, stderr_log: Path) -> str:
        return self.run_prompt(repository, context_file, stdout_log, stderr_log, None)

    def run_prompt(
        self,
        repository: Path,
        context_file: Path,
        stdout_log: Path,
        stderr_log: Path,
        prompt: str | None,
    ) -> str:
        if shutil.which(self.executable) is None and not Path(self.executable).is_file():
            raise OpenCodeError(
                f"未找到 OpenCode 可执行文件 '{self.executable}'。请安装 OpenCode，或使用 --opencode-executable 指向企业兼容启动器。"
            )
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            # Pass the generated context over stdin and keep cwd at the source
            # repository. The task-specific agent has no tools, so it cannot read
            # credentials or modify files; ClangWiki remains the sole writer.
            context = context_file.read_text(encoding="utf-8")
            environment = os.environ.copy()
            if not self.agent or self.agent == "clangwiki-doc":
                # Every document task gets its own temporary OpenCode config.
                # Leaf tasks may run concurrently, so a shared config filename
                # would introduce a needless write race in the task directory.
                runtime_config = context_file.with_suffix(".opencode.json")
                runtime_config.write_text(
                    json.dumps(
                        {
                            "$schema": "https://opencode.ai/config.json",
                            "agent": {
                                "clangwiki-doc": {
                                    "description": "Generate one document only from bounded ClangWiki evidence on stdin",
                                    "mode": "primary",
                                    "prompt": (
                                        "You are ClangWiki's deterministic documentation writer. The complete task context "
                                        "arrives on standard input. Do not call tools, inspect the repository, launch "
                                        "subagents, or use network access. Produce only the requested final Markdown."
                                    ),
                                    "permission": {"*": "deny"},
                                }
                            },
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                environment["OPENCODE_CONFIG"] = str(runtime_config)
            result = subprocess.run(self.command(context_file, prompt), cwd=repository, input=context, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=self.timeout_seconds,
                creationflags=flags, check=False, env=environment)
        except subprocess.TimeoutExpired as exc:
            raise OpenCodeError(f"opencode run 在 {self.timeout_seconds} 秒内未完成。") from exc
        write_text(stdout_log, result.stdout)
        write_text(stderr_log, result.stderr)
        if result.returncode != 0:
            detail = _diagnostic_excerpt(result.stderr) or _diagnostic_excerpt(result.stdout)
            suffix = f"\nOpenCode 输出：{detail}" if detail else ""
            raise OpenCodeError(f"opencode run 失败（退出码 {result.returncode}）。日志：{stderr_log}{suffix}")
        output = result.stdout.strip()
        if not output:
            detail = _diagnostic_excerpt(result.stderr)
            suffix = f"\nOpenCode 输出：{detail}" if detail else ""
            raise OpenCodeError(f"opencode run 返回空输出。日志：{stderr_log}{suffix}")
        return output


def _diagnostic_excerpt(value: str, limit: int = 1600) -> str:
    """Return a bounded, single-line diagnostic suitable for the local task UI."""
    without_ansi = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    cleaned = "\n".join(line.rstrip() for line in without_ansi.strip().splitlines() if line.strip())
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")
