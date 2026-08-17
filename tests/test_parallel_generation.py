from __future__ import annotations

import threading
import time
from pathlib import Path

from clangwiki.models import AnalysisBundle, DocumentTask, Module, RunConfig
from clangwiki.pipeline import GenerationPipeline


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.started = threading.Event()
        self.release = threading.Event()
        self.lock = threading.Lock()

    def generate(self, _repository: Path, context_file: Path, _stdout: Path, _stderr: Path) -> str:
        task_id = context_file.stem
        with self.lock:
            self.calls.append(task_id)
            if len(self.calls) >= 2:
                self.started.set()
        if task_id.startswith("leaf-"):
            self.release.wait(timeout=2)
        return "# Generated\n\n## 模块概述\n当前证据无法确定。"


def test_leaf_generation_runs_in_parallel_before_aggregate(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("a.c", "b.c"):
        (repo / name).write_text("int run(void) { return 0; }\n", encoding="utf-8")
    config = RunConfig(
        repo=repo,
        workspace=tmp_path / "workspace",
        output=tmp_path / "output",
        build_dir=tmp_path / "build",
        model="test/model",
        module_generation_concurrency=2,
        overwrite=True,
    )
    pipeline = GenerationPipeline(config)
    runner = _RecordingRunner()
    leaves = {
        "a": Module("a", "A", ["a.c"], [], source_path="a", is_leaf=True),
        "b": Module("b", "B", ["b.c"], [], source_path="b", is_leaf=True),
        "parent": Module("parent", "Parent", [], [], source_path=".", child_ids=("a", "b"), is_leaf=False),
    }
    tasks = [
        DocumentTask("leaf-a", "leaf-module", "A", "Modules/a.md", ("a",), hierarchy_role="leaf"),
        DocumentTask("leaf-b", "leaf-module", "B", "Modules/b.md", ("b",), hierarchy_role="leaf"),
        DocumentTask(
            "summary-parent", "module-summary", "Parent", "Modules/index.md", ("parent",),
            hierarchy_role="aggregate", child_document_paths=("Modules/a.md", "Modules/b.md"),
        ),
    ]
    events: list[dict[str, object]] = []
    pipeline.progress_sink = events.append

    def fake_context(task, _repo, _modules, _analysis, output, *_args):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"# Context {task.task_id}\n", encoding="utf-8")
        return output

    def fake_validate(_markdown: str, _document_type: str, _child_documents=None) -> None:
        return None

    monkeypatch.setattr("clangwiki.pipeline.build_context", fake_context)
    monkeypatch.setattr("clangwiki.pipeline.validate_markdown", fake_validate)

    completed: list[Path] = []

    def invoke() -> None:
        completed.extend(pipeline._generate_documents(
            tasks, runner, repo, config.workspace, leaves, AnalysisBundle("full"), config.workspace / "pipeline.log",
        ))

    thread = threading.Thread(target=invoke)
    thread.start()
    assert runner.started.wait(timeout=1), "two leaf OpenCode calls should start together"
    assert "summary-parent" not in runner.calls
    runner.release.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert runner.calls[-1] == "summary-parent"
    assert [path.name for path in completed] == ["a.md", "b.md", "index.md"]
    assert any(event["stage"] == "parallel" for event in events)
