from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from .database import Database, json_dumps, json_loads
from .document_schema import DOCUMENT_SCHEMAS
from .errors import ClangWikiError
from .graph import GraphService
from .indexing import IndexService
from .models import RunConfig, normalize_module_generation_concurrency
from .opencode import OpenCodeRunner
from .output import validate_markdown
from .pipeline import GenerationPipeline
from .registry import Registry, git_identity
from .wiki import WikiService


DOCUMENT_SCHEMA_VERSION = "2026.08-aord"
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}
EXCLUDED_DIRS = {".git", "build", "dist", "node_modules", "third_party", "vendor", ".clangwiki"}


class PlatformGenerationService:
    def __init__(
        self,
        database: Database,
        registry: Registry,
        graph: GraphService,
        wiki: WikiService,
        indexer: IndexService,
    ) -> None:
        self.db = database
        self.registry = registry
        self.graph = graph
        self.wiki = wiki
        self.indexer = indexer

    def generate_repository(
        self,
        repository_id: str,
        overrides: dict[str, Any] | None = None,
        progress: Callable[[dict[str, object]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        repository = self.registry.get_repository(repository_id)
        config = {**repository["config"], **(overrides or {})}
        model = str(config.get("model") or "").strip()
        if not model:
            raise ClangWikiError("仓库未配置 OpenCode 模型标识。")
        concurrency = _module_generation_concurrency(config.get("module_generation_concurrency"))
        source_root = Path(repository["path"])
        current_hashes = repository_file_hashes(source_root)
        config_hash = _hash_json(self._generation_config(config))
        previous = repository.get("active_run")
        previous_manifest = previous.get("manifest", {}) if previous else {}
        force = bool(config.get("force"))
        changed_paths = _changed_paths(previous_manifest.get("file_hashes", {}), current_hashes)
        if previous and not force and not changed_paths and previous.get("config_hash") == config_hash:
            self.db.execute(
                "UPDATE repositories SET status='ready',updated_at=? WHERE id=?",
                (time.time(), repository_id),
            )
            if progress:
                progress({"stage": "unchanged", "message": "代码和生成配置均未变化，继续使用当前文档快照。", "progress": 100})
            return {"run": previous, "reused": True, "changed_paths": []}

        run_id = f"run-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        run_root = self.registry.run_root(repository_id, run_id)
        run_root.mkdir(parents=True, exist_ok=False)
        if previous:
            previous_root = Path(previous["artifact_path"])
            incremental = bool(changed_paths) and not self._requires_full_rebuild(changed_paths, previous_manifest, config_hash)
            if incremental:
                previous_output = previous_root / "output"
                if previous_output.is_dir():
                    shutil.copytree(previous_output, run_root / "output", dirs_exist_ok=True)
            # An explicit skip flag means the caller deliberately requests reuse of
            # the immutable prior snapshot.  Each run still writes to a fresh directory.
            if config.get("skip_cmake") and (previous_root / "build").is_dir():
                shutil.copytree(previous_root / "build", run_root / "build", dirs_exist_ok=True)
            if config.get("skip_analysis") and (previous_root / "analysis").is_dir():
                shutil.copytree(previous_root / "analysis", run_root / "analysis", dirs_exist_ok=True)
        module_ids = self._affected_modules(previous, changed_paths)
        full_rebuild = not previous or not module_ids or self._requires_full_rebuild(changed_paths, previous_manifest, config_hash)
        if full_rebuild:
            module_ids = ()
        branch, commit = git_identity(source_root)
        manifest = {
            "file_hashes": current_hashes,
            "changed_paths": changed_paths,
            "full_rebuild": full_rebuild,
            "affected_module_ids": list(module_ids),
            "git_branch": branch,
            "git_commit": commit,
            "config_hash": config_hash,
            "schema_version": DOCUMENT_SCHEMA_VERSION,
            "embedding_profile": config.get("embedding_profile", "balanced"),
            "module_generation_concurrency": concurrency,
        }
        now = time.time()
        self.db.execute(
            "INSERT INTO runs(id,repository_id,status,git_commit,config_hash,schema_version,embedding_model,artifact_path,manifest_json,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, repository_id, "running", commit, config_hash, DOCUMENT_SCHEMA_VERSION,
                config.get("embedding_profile", "balanced"), str(run_root), json_dumps(manifest), now,
            ),
        )
        self.db.execute("UPDATE repositories SET status='generating',updated_at=? WHERE id=?", (now, repository_id))
        try:
            run_config = RunConfig(
                repo=source_root,
                workspace=run_root,
                output=run_root / "output",
                build_dir=run_root / "build",
                model=model,
                opencode_executable=str(config.get("opencode_executable") or "opencode"),
                agent=str(config.get("agent") or "") or None,
                timeout_seconds=int(config.get("timeout_seconds") or 900),
                language=str(config.get("language") or "简体中文"),
                max_source_chars_per_task=int(config.get("max_source_chars_per_task") or 36000),
                module_generation_concurrency=concurrency,
                overwrite=True,
                skip_cmake=bool(config.get("skip_cmake", False)),
                skip_analysis=bool(config.get("skip_analysis", False)),
                only=tuple(config.get("only") or ()),
                module_ids=tuple(module_ids),
                leaf_module_paths=tuple(config.get("leaf_module_paths") or ()),
                channel_module_paths=tuple(config.get("channel_module_paths") or ()),
            )
            outputs = GenerationPipeline(
                run_config,
                str(config.get("analyzer_executable") or "") or None,
                progress_sink=progress,
                cancel_event=cancel_event,
            ).run()
            compilation_database = run_root / "build" / "compile_commands.json"
            manifest["compile_commands_hash"] = _file_hash(compilation_database) if compilation_database.is_file() else None
            manifest["outputs"] = [str(path.relative_to(run_root / "output").as_posix()) for path in outputs]
            manifest["completed_at"] = time.time()
            (run_root / "manifest.json").write_text(json_dumps(manifest) + "\n", encoding="utf-8")
            self.db.execute(
                "UPDATE runs SET status='completed',manifest_json=?,finished_at=? WHERE id=?",
                (json_dumps(manifest), time.time(), run_id),
            )
            self.db.execute(
                "UPDATE repositories SET status='ready',active_run_id=?,git_branch=?,git_commit=?,updated_at=? WHERE id=?",
                (run_id, branch, commit, time.time(), repository_id),
            )
            if progress:
                progress({"stage": "graph", "message": "正在写入模块、文件与符号关系图", "progress": 95})
            graph_result = self.graph.ingest_repository(repository_id, run_id, run_root)
            if progress:
                progress({"stage": "wiki", "message": "正在登记 Wiki 快照与导航信息", "progress": 97})
            documents = self.wiki.ingest_generated(repository_id, run_id, run_root)
            index_result: dict[str, Any] | None = None
            if config.get("build_index", True):
                if progress:
                    progress({"stage": "index", "message": "正在构建混合知识索引", "progress": 98})
                index_result = self.indexer.index_repository(repository_id, str(config.get("embedding_profile") or "balanced"))
            return {
                "run": self.get_run(run_id), "reused": False, "changed_paths": changed_paths,
                "graph": graph_result, "documents": len(documents), "index": index_result,
            }
        except Exception as exc:
            self.db.execute(
                "UPDATE runs SET status='failed',manifest_json=?,finished_at=? WHERE id=?",
                (json_dumps({**manifest, "error": str(exc)}), time.time(), run_id),
            )
            # A failed/cancelled attempt remains visible in run history, but it
            # must not make an existing successful Wiki snapshot look unusable.
            repository_status = "ready" if previous and previous.get("status") == "completed" else "failed"
            self.db.execute(
                "UPDATE repositories SET status=?,updated_at=? WHERE id=?",
                (repository_status, time.time(), repository_id),
            )
            raise

    def list_runs(self, repository_id: str) -> list[dict[str, Any]]:
        self.registry.get_repository(repository_id)
        return [self._public_run(row) for row in self.db.all(
            "SELECT * FROM runs WHERE repository_id=? ORDER BY created_at DESC", (repository_id,)
        )]

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM runs WHERE id=?", (run_id,))
        if not row:
            raise KeyError("运行记录不存在")
        return self._public_run(row)

    def activate_run(self, repository_id: str, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run["repository_id"] != repository_id or run["status"] != "completed":
            raise ValueError("只能激活当前仓库中已成功完成的运行。")
        run_root = Path(run["artifact_path"])
        self.db.execute(
            "UPDATE repositories SET active_run_id=?,status='ready',updated_at=? WHERE id=?",
            (run_id, time.time(), repository_id),
        )
        self.graph.ingest_repository(repository_id, run_id, run_root)
        self.wiki.ingest_generated(repository_id, run_id, run_root)
        self.indexer.index_repository(repository_id)
        return self.registry.get_repository(repository_id)

    @staticmethod
    def _public_run(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["manifest"] = json_loads(result.pop("manifest_json"), {})
        return result

    @staticmethod
    def _generation_config(config: dict[str, Any]) -> dict[str, Any]:
        # CLI flags explicitly carry false/empty defaults while the HTTP API omits
        # them.  Canonicalise both entry points before hashing so an unchanged
        # repository does not accidentally start another expensive model run.
        only = sorted({str(item) for item in (config.get("only") or ()) if str(item)})
        channel_paths = sorted({str(item) for item in (config.get("channel_module_paths") or ()) if str(item)})
        leaf_paths = sorted({str(item) for item in (config.get("leaf_module_paths") or ()) if str(item)})
        return {
            "agent": str(config.get("agent") or ""),
            "channel_module_paths": channel_paths,
            "language": str(config.get("language") or "简体中文"),
            "leaf_module_paths": leaf_paths,
            "max_source_chars_per_task": int(config.get("max_source_chars_per_task") or 36000),
            "model": str(config.get("model") or "").strip(),
            "only": only or None,
            "skip_analysis": bool(config.get("skip_analysis", False)),
            "skip_cmake": bool(config.get("skip_cmake", False)),
        }

    @staticmethod
    def _requires_full_rebuild(changed_paths: list[str], previous_manifest: dict[str, Any], config_hash: str) -> bool:
        if previous_manifest.get("config_hash") != config_hash:
            return True
        return any(
            Path(path).name in {"CMakeLists.txt", "compile_commands.json"}
            or path.endswith(".cmake") for path in changed_paths
        )

    def _affected_modules(self, previous: dict[str, Any] | None, changed_paths: list[str]) -> tuple[str, ...]:
        if not previous or not changed_paths:
            return ()
        root = Path(previous["artifact_path"])
        try:
            modules = json.loads((root / "knowledge" / "modules.json").read_text(encoding="utf-8"))
            relations = json.loads((root / "knowledge" / "relations.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()
        changed = set(changed_paths)
        headers = {Path(path).name for path in changed if Path(path).suffix.lower() in {".h", ".hh", ".hpp", ".hxx"}}
        for relation in relations:
            if relation.get("kind") == "INCLUDES" and Path(str(relation.get("target") or "")).name in headers:
                changed.add(str(relation.get("file_path") or ""))
        direct_owner: dict[str, str] = {}
        parent: dict[str, str | None] = {}
        source_paths: list[tuple[str, str]] = []
        for module in modules:
            module_id = str(module.get("module_id"))
            parent[module_id] = str(module.get("parent_id")) if module.get("parent_id") else None
            source_paths.append((str(module.get("source_path") or ""), module_id))
            for path in module.get("direct_files") or []:
                direct_owner[str(path)] = module_id
        affected: set[str] = set()
        for path in changed:
            owner = direct_owner.get(path)
            if owner is None:
                candidates = [(len(source), module_id) for source, module_id in source_paths if source and path.startswith(source + "/")]
                owner = max(candidates, default=(0, None))[1]
            if owner is None:
                return ()
            while owner:
                affected.add(owner)
                owner = parent.get(owner)
        return tuple(sorted(affected))


class CollectionGenerationService:
    DOCUMENTS = {
        "CollectionOverview.md": (
            "知识空间总览",
            ("知识空间定位", "成员仓库", "整体能力", "跨仓业务主线", "Wiki 导航", "证据与覆盖限制"),
        ),
        "RepositoryIndex.md": (
            "成员仓库索引",
            ("仓库清单", "仓库职责", "关键模块", "仓库间依赖", "推荐阅读顺序", "证据限制"),
        ),
        "CrossRepositoryArchitecture.md": (
            "跨仓架构",
            ("架构边界", "仓库分层", "跨仓依赖", "公共接口", "数据与控制流", "风险与待确认项"),
        ),
        "CrossRepositoryInterfaces.md": (
            "跨仓接口",
            ("接口索引", "确定接口关系", "候选接口关系", "共享数据结构", "配置传播", "证据与限制"),
        ),
        "CrossRepositoryCallFlows.md": (
            "跨仓调用流程",
            ("流程索引", "触发条件", "确定调用链", "候选调用", "失败路径", "证据与覆盖限制"),
        ),
    }

    def __init__(
        self,
        database: Database,
        registry: Registry,
        graph: GraphService,
        wiki: WikiService,
        indexer: IndexService,
    ) -> None:
        self.db = database
        self.registry = registry
        self.graph = graph
        self.wiki = wiki
        self.indexer = indexer

    def generate(
        self,
        collection_id: str,
        overrides: dict[str, Any] | None = None,
        progress: Callable[[dict[str, object]], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        collection = self.registry.get_collection(collection_id)
        repositories = collection["repositories"]
        if not repositories:
            raise ClangWikiError("知识空间中尚未加入代码仓。")
        settings = {**repositories[0]["config"], **collection.get("config", {}), **(overrides or {})}
        model = str(settings.get("model") or "").strip()
        if not model:
            raise ClangWikiError("知识空间未获得可用的 OpenCode 模型配置。")
        graph_result = self.graph.rebuild_collection(collection_id)
        context = self._context(collection)
        root = self.registry.collection_root(collection_id)
        task_root = root / "tasks"
        log_root = root / "logs" / "opencode"
        task_root.mkdir(parents=True, exist_ok=True)
        runner = OpenCodeRunner(
            str(settings.get("opencode_executable") or "opencode"), model,
            str(settings.get("agent") or "") or None, int(settings.get("timeout_seconds") or 900),
        )
        generated = []
        for index, (relative, (title, sections)) in enumerate(self.DOCUMENTS.items(), start=1):
            if cancel_event and cancel_event.is_set():
                raise ClangWikiError("集合文档生成已取消。")
            context_file = task_root / f"{Path(relative).stem}.md"
            section_contract = "\n".join(f"{number}. `## {heading}`" for number, heading in enumerate(sections, 1))
            context_file.write_text(
                "# ClangWiki Collection Task\n\n"
                f"文档：{title}\n\n必须严格按顺序输出以下二级章节：\n{section_contract}\n\n"
                "确定关系与候选关系必须分开；不得虚构跨仓调用。\n\n## 可用证据\n\n" + context,
                encoding="utf-8",
            )
            prompt = "依据附件生成集合级 Markdown 文档。只输出正文；每个结论给出成员仓库和文档来源，证据不足时明确说明。"
            stdout = log_root / f"{Path(relative).stem}.stdout.txt"
            stderr = log_root / f"{Path(relative).stem}.stderr.txt"
            markdown = runner.run_prompt(Path(repositories[0]["path"]), context_file, stdout, stderr, prompt)
            validate_markdown(markdown)
            self._validate_sections(markdown, sections)
            generated.append(self.wiki.ingest_collection_document(collection_id, title, markdown, relative))
            if progress:
                progress({
                    "stage": "collection-document", "message": f"已生成 {title}",
                    "progress": int(index / len(self.DOCUMENTS) * 90),
                })
        index_result = self.indexer.index_collection(collection_id, str(settings.get("embedding_profile") or "balanced"))
        return {"documents": generated, "graph": graph_result, "index": index_result}

    def _context(self, collection: dict[str, Any], budget: int = 180000) -> str:
        blocks = [f"# 知识空间：{collection['name']}", collection.get("description") or ""]
        used = sum(len(item) for item in blocks)
        for repository in collection["repositories"]:
            blocks.append(f"\n## 仓库：{repository['name']}\n路径：{repository['path']}\n")
            documents = self.db.all(
                "SELECT title,relative_path,content FROM documents WHERE repository_id=? AND run_id=? ORDER BY relative_path",
                (repository["id"], repository.get("active_run_id")),
            )
            for document in documents:
                content = str(document.get("content") or "")
                block = f"\n### {document['title']} (`{repository['name']}/{document['relative_path']}`)\n{content}\n"
                if used + len(block) > budget:
                    blocks.append("\n> 集合上下文达到预算上限，其余内容未附加；不得推测缺失实现。")
                    return "\n".join(blocks)
                blocks.append(block)
                used += len(block)
        return "\n".join(blocks)

    @staticmethod
    def _validate_sections(markdown: str, sections: tuple[str, ...]) -> None:
        actual = tuple(line[3:].strip() for line in markdown.splitlines() if line.startswith("## "))
        if actual != sections:
            raise ClangWikiError(f"集合文档章节不符合契约。期望 {list(sections)}，实际 {list(actual)}")


def repository_file_hashes(root: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRS for part in relative.parts):
            continue
        if path.suffix.lower() not in SOURCE_SUFFIXES | {".cmake", ".txt"} and path.name != "CMakeLists.txt":
            continue
        values[relative.as_posix()] = _file_hash(path)
    return values


def _changed_paths(previous: dict[str, str], current: dict[str, str]) -> list[str]:
    return sorted({*previous, *current} - {path for path in previous.keys() & current.keys() if previous[path] == current[path]})


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _hash_json(value: Any) -> str:
    return hashlib.sha256(json_dumps(value).encode("utf-8")).hexdigest()


def _module_generation_concurrency(value: Any) -> int:
    """Validate the bounded local OpenCode fan-out for one repository run."""
    # Keep this private compatibility wrapper for callers that imported the
    # helper from platform before validation was centralised in models.py.
    return normalize_module_generation_concurrency(value)
