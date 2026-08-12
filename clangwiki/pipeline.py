from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from .analyzer import ClangAnalyzer
from .build import (
    configure_cmake,
    create_fallback_compilation_database,
    validate_compilation_database,
    validate_repository,
)
from .context import build_context
from .errors import CMakeError, ClangWikiError, CompilationDatabaseError, GenerationCancelled
from .io import read_json, write_json, write_text
from .knowledge import build_knowledge
from .models import AnalysisBundle, RunConfig
from .opencode import OpenCodeRunner
from .output import validate_markdown, write_document
from .planner import plan_documents


class GenerationPipeline:
    def __init__(
        self,
        config: RunConfig,
        analyzer_executable: str | None = None,
        progress_sink: Callable[[dict[str, object]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.config = config
        self.analyzer_executable = analyzer_executable
        self.progress_sink = progress_sink
        self.cancel_event = cancel_event

    def _emit(self, stage: str, message: str, progress: int | None = None) -> None:
        if self.progress_sink is not None:
            self.progress_sink({"stage": stage, "message": message, "progress": progress})

    def _check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise GenerationCancelled("ClangWiki generation was cancelled")

    def run(self) -> list[Path]:
        cfg = self.config
        self._check_cancelled()
        self._emit("prepare", "正在校验代码仓与生成配置", 3)
        repo = validate_repository(cfg.repo)
        workspace = cfg.workspace.expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        log = workspace / "logs" / "pipeline.log"
        write_text(log, "[START] ClangWiki pipeline started\n")
        self._emit("cmake", "正在准备 CMake 编译数据库", 8)
        compilation_database, partial_build_reason = self._compilation_database(repo)
        if partial_build_reason:
            self._log(log, f"[CMAKE FALLBACK] {partial_build_reason}")
            self._emit(
                "cmake-fallback",
                "子仓无法独立执行 CMake，已生成后备编译数据库并切换为部分分析。原因："
                + " ".join(partial_build_reason.split())[:700],
                14,
            )
        self._log(log, f"[BUILD] compilation database: {compilation_database}")
        self._emit("cmake", "CMake 编译数据库已准备完成", 16)
        self._check_cancelled()
        self._emit("clang", "正在执行 Clang 静态分析", 20)
        analysis = self._analysis(repo, compilation_database)
        self._log(log, f"[ANALYZE] mode={analysis.mode}, symbols={len(analysis.symbols)}, relations={len(analysis.relations)}")
        self._emit("clang", f"Clang 分析完成：{len(analysis.symbols)} 个符号，{len(analysis.relations)} 条关系", 32)
        self._check_cancelled()
        self._emit("modules", "正在构建模块层级与叶子文档边界", 36)
        modules = build_knowledge(
            repo,
            compilation_database,
            analysis,
            workspace / "knowledge",
            cfg.leaf_module_paths,
            cfg.channel_module_paths,
        )
        tasks = plan_documents(modules, cfg.only, cfg.module_ids)
        write_json(workspace / "tasks" / "tasks.json", [task.__dict__ for task in tasks])
        self._log(log, f"[PLAN] {len(tasks)} document tasks")
        self._emit("plan", f"文档计划已生成：共 {len(tasks)} 个任务", 42)
        runner = OpenCodeRunner(cfg.opencode_executable, cfg.model, cfg.agent, cfg.timeout_seconds)
        generated: list[Path] = []
        document_span = 52
        for index, task in enumerate(tasks, start=1):
            self._check_cancelled()
            context_file = workspace / "tasks" / "contexts" / f"{task.task_id}.md"
            build_context(
                task,
                repo,
                modules,
                analysis,
                context_file,
                cfg.language,
                cfg.max_source_chars_per_task,
                cfg.output,
            )
            self._log(log, f"[CONTEXT] {context_file.name}")
            start_progress = 42 + int((index - 1) / max(1, len(tasks)) * document_span)
            end_progress = 42 + int(index / max(1, len(tasks)) * document_span)
            self._emit("context", f"正在整理上下文（{index}/{len(tasks)}）：{task.title}", start_progress)
            stdout_log = workspace / "logs" / "opencode" / f"{task.task_id}.stdout.txt"
            stderr_log = workspace / "logs" / "opencode" / f"{task.task_id}.stderr.txt"
            try:
                self._emit("opencode", f"正在调用 OpenCode 生成（{index}/{len(tasks)}）：{task.title}", min(end_progress - 2, start_progress + 1))
                markdown = runner.generate(repo, context_file, stdout_log, stderr_log)
                self._emit("validate", f"正在校验 Markdown（{index}/{len(tasks)}）：{task.title}", max(start_progress, end_progress - 1))
                validate_markdown(markdown, task.document_type)
                destination = write_document(cfg.output, task.output_relative_path, markdown, cfg.overwrite)
            except ClangWikiError as exc:
                self._log(log, f"[FAILED] {task.task_id}; logs: {stdout_log}, {stderr_log}")
                raise type(exc)(f"文档任务“{task.title}”失败：{exc}") from exc
            generated.append(destination)
            self._log(log, f"[OUTPUT] {destination}")
            self._emit("document", f"已生成（{index}/{len(tasks)}）：{task.title}", end_progress)
        self._log(log, "[DONE] ClangWiki pipeline completed")
        self._emit("documents", f"模块 Wiki 已生成：共 {len(generated)} 篇文档", 94)
        return generated

    def _compilation_database(self, repo: Path) -> tuple[Path, str | None]:
        build_dir = self.config.build_dir.expanduser().resolve()
        if self.config.skip_cmake:
            return validate_compilation_database(build_dir / "compile_commands.json"), None
        try:
            return configure_cmake(repo, build_dir), None
        except (CMakeError, CompilationDatabaseError) as exc:
            return create_fallback_compilation_database(repo, build_dir), str(exc)

    def _analysis(self, repo: Path, compilation_database: Path) -> AnalysisBundle:
        artifact_dir = self.config.workspace.expanduser().resolve() / "analysis"
        if self.config.skip_analysis:
            return AnalysisBundle(
                mode=read_json(artifact_dir / "diagnostics.json").get("mode", "cached"),
                diagnostics=read_json(artifact_dir / "diagnostics.json").get("diagnostics", []),
                files=read_json(artifact_dir / "files.json"),
                symbols=read_json(artifact_dir / "symbols.json"),
                relations=read_json(artifact_dir / "relations.json"),
            )
        return ClangAnalyzer(self.analyzer_executable).analyze(repo, compilation_database, artifact_dir)

    @staticmethod
    def _log(path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(line + "\n")
