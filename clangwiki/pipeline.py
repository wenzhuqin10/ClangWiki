from __future__ import annotations

from pathlib import Path

from .analyzer import ClangAnalyzer
from .build import configure_cmake, validate_compilation_database, validate_repository
from .context import build_context
from .errors import ClangWikiError
from .io import read_json, write_json, write_text
from .knowledge import build_knowledge
from .models import AnalysisBundle, RunConfig
from .opencode import OpenCodeRunner
from .output import validate_markdown, write_document
from .planner import plan_documents


class GenerationPipeline:
    def __init__(self, config: RunConfig, analyzer_executable: str | None = None) -> None:
        self.config = config
        self.analyzer_executable = analyzer_executable

    def run(self) -> list[Path]:
        cfg = self.config
        repo = validate_repository(cfg.repo)
        workspace = cfg.workspace.expanduser().resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        log = workspace / "logs" / "pipeline.log"
        write_text(log, "[START] ClangWiki pipeline started\n")
        compilation_database = self._compilation_database(repo)
        self._log(log, f"[BUILD] compilation database: {compilation_database}")
        analysis = self._analysis(repo, compilation_database)
        self._log(log, f"[ANALYZE] mode={analysis.mode}, symbols={len(analysis.symbols)}, relations={len(analysis.relations)}")
        modules = build_knowledge(
            repo,
            compilation_database,
            analysis,
            workspace / "knowledge",
            cfg.leaf_module_paths,
        )
        tasks = plan_documents(modules, cfg.only)
        write_json(workspace / "tasks" / "tasks.json", [task.__dict__ for task in tasks])
        self._log(log, f"[PLAN] {len(tasks)} document tasks")
        runner = OpenCodeRunner(cfg.opencode_executable, cfg.model, cfg.agent, cfg.timeout_seconds)
        generated: list[Path] = []
        for task in tasks:
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
            stdout_log = workspace / "logs" / "opencode" / f"{task.task_id}.stdout.txt"
            stderr_log = workspace / "logs" / "opencode" / f"{task.task_id}.stderr.txt"
            try:
                markdown = runner.generate(repo, context_file, stdout_log, stderr_log)
                validate_markdown(markdown, task.document_type)
                destination = write_document(cfg.output, task.output_relative_path, markdown, cfg.overwrite)
            except ClangWikiError:
                self._log(log, f"[FAILED] {task.task_id}; logs: {stdout_log}, {stderr_log}")
                raise
            generated.append(destination)
            self._log(log, f"[OUTPUT] {destination}")
        self._log(log, "[DONE] ClangWiki pipeline completed")
        return generated

    def _compilation_database(self, repo: Path) -> Path:
        build_dir = self.config.build_dir.expanduser().resolve()
        if self.config.skip_cmake:
            return validate_compilation_database(build_dir / "compile_commands.json")
        return configure_cmake(repo, build_dir)

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
