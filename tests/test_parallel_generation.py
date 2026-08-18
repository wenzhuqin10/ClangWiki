from __future__ import annotations

import json
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


class _ImmediateRunner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate(self, _repository: Path, context_file: Path, _stdout: Path, _stderr: Path) -> str:
        self.calls.append(context_file.stem)
        return "# Generated\n\nBody\n"


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
        DocumentTask("leaf-a", "leaf-engineering", "A", "Modules/a.md", ("a",), hierarchy_role="leaf"),
        DocumentTask("leaf-b", "leaf-engineering", "B", "Modules/b.md", ("b",), hierarchy_role="leaf"),
        DocumentTask(
            "summary-parent", "subsystem-guide", "Parent", "Modules/index.md", ("parent",),
            hierarchy_role="subsystem", child_document_paths=("Modules/a.md", "Modules/b.md"),
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


def test_resume_reuses_checkpointed_documents_and_continues_remaining_tasks(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.c").write_text("int a(void) { return 0; }\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    output = workspace / "output"
    completed_path = output / "Modules" / "a.md"
    completed_path.parent.mkdir(parents=True)
    completed_path.write_text("# Existing A\n\nBody\n", encoding="utf-8")
    (workspace / "checkpoint.json").write_text(json.dumps({
        "completed_task_ids": ["leaf-a"], "completed": 1, "total": 2,
    }), encoding="utf-8")
    config = RunConfig(
        repo=repo, workspace=workspace, output=output, build_dir=workspace / "build",
        model="test/model", overwrite=True, resume=True,
    )
    pipeline = GenerationPipeline(config)
    runner = _ImmediateRunner()
    modules = {
        "a": Module("a", "A", ["a.c"], [], source_path="a", is_leaf=True),
        "parent": Module("parent", "Parent", [], [], source_path=".", child_ids=("a",), is_leaf=False),
    }
    tasks = [
        DocumentTask("leaf-a", "leaf-engineering", "A", "Modules/a.md", ("a",), hierarchy_role="leaf"),
        DocumentTask(
            "summary-parent", "subsystem-guide", "Parent", "Modules/index.md", ("parent",),
            hierarchy_role="subsystem", child_document_paths=("Modules/a.md",),
        ),
    ]
    events: list[dict[str, object]] = []
    pipeline.progress_sink = events.append

    def fake_context(task, _repo, _modules, _analysis, destination, *_args):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"# Context {task.task_id}\n", encoding="utf-8")

    monkeypatch.setattr("clangwiki.pipeline.build_context", fake_context)
    monkeypatch.setattr("clangwiki.pipeline.validate_markdown", lambda *_args, **_kwargs: None)
    generated = pipeline._generate_documents(
        tasks, runner, repo, workspace, modules, AnalysisBundle("cached"), workspace / "pipeline.log",
    )

    assert runner.calls == ["summary-parent"]
    assert generated == [completed_path, output / "Modules" / "index.md"]
    assert any(event["stage"] == "resume" for event in events)
    checkpoint = json.loads((workspace / "checkpoint.json").read_text(encoding="utf-8"))
    assert checkpoint["completed_task_ids"] == ["leaf-a", "summary-parent"]
