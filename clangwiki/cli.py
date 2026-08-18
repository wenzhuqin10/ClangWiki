from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .api import build_services
from .errors import ClangWikiError
from .models import RunConfig, normalize_module_generation_concurrency
from .pipeline import GenerationPipeline


def _default_data_root() -> Path:
    configured = os.environ.get("CLANGWIKI_DATA_ROOT")
    if configured:
        return Path(configured).expanduser()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "ClangWiki" / "data"
    return Path.home() / ".clangwiki" / "data"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="clangwiki",
        description="Clang 驱动的本地多仓 C/C++ 知识平台；模型调用仅通过 opencode run。",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-root", type=Path, default=_default_data_root(), help="平台数据根目录")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="启动中文可视化工作台")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8082)
    serve.add_argument("--repo", type=Path, help="兼容参数：启动前自动注册该仓库")
    _repository_config_arguments(serve, require_model=False)

    repo = commands.add_parser("repo", help="管理本地代码仓")
    repo_commands = repo.add_subparsers(dest="repo_command", required=True)
    repo_add = repo_commands.add_parser("add", help="注册代码仓，不复制源码")
    repo_add.add_argument("path", type=Path)
    repo_add.add_argument("--name")
    _repository_config_arguments(repo_add, require_model=False)
    repo_commands.add_parser("list", help="列出仓库")
    repo_show = repo_commands.add_parser("show", help="查看仓库")
    repo_show.add_argument("repository_id")
    repo_update = repo_commands.add_parser("update", help="更新仓库配置")
    repo_update.add_argument("repository_id")
    repo_update.add_argument("--name")
    _repository_config_arguments(repo_update, require_model=False)
    repo_remove = repo_commands.add_parser("remove", help="删除注册记录，永不删除源码")
    repo_remove.add_argument("repository_id")
    repo_remove.add_argument("--purge-artifacts", action="store_true", help="同时删除平台生成物和索引")

    collection = commands.add_parser("collection", help="管理逻辑知识空间")
    collection_commands = collection.add_subparsers(dest="collection_command", required=True)
    collection_create = collection_commands.add_parser("create")
    collection_create.add_argument("name")
    collection_create.add_argument("--description", default="")
    collection_create.add_argument("--repo-id", action="append", default=[])
    collection_commands.add_parser("list")
    collection_show = collection_commands.add_parser("show")
    collection_show.add_argument("collection_id")
    collection_add = collection_commands.add_parser("add")
    collection_add.add_argument("collection_id")
    collection_add.add_argument("repository_id")
    collection_remove = collection_commands.add_parser("remove")
    collection_remove.add_argument("collection_id")
    collection_remove.add_argument("repository_id", nargs="?")
    collection_remove.add_argument("--delete-collection", action="store_true")
    collection_generate = collection_commands.add_parser("generate", help="生成集合级 Wiki")
    collection_generate.add_argument("collection_id")
    collection_generate.add_argument("--force", action="store_true")
    collection_rebuild = collection_commands.add_parser("rebuild-relations", help="重建跨仓确定/候选关系")
    collection_rebuild.add_argument("collection_id")

    generate = commands.add_parser("generate", help="生成仓库 Wiki")
    target = generate.add_mutually_exclusive_group(required=True)
    target.add_argument("--repo-id")
    target.add_argument("--collection-id")
    target.add_argument("--repo", type=Path, help="兼容旧版的一次性生成")
    generate.add_argument("--workspace", type=Path, default=Path("workspace"))
    generate.add_argument("--output", type=Path)
    generate.add_argument("--build-dir", type=Path)
    _repository_config_arguments(generate, require_model=False)
    generate.add_argument("--overwrite", action="store_true")
    generate.add_argument("--force", action="store_true")
    generate.add_argument("--skip-cmake", action="store_true")
    generate.add_argument("--skip-analysis", action="store_true")
    generate.add_argument(
        "--only", action="append",
        choices=[
            "readme", "architecture", "module", "leaf-module", "module-summary",
            "repository-guide", "subsystem-guide", "channel-playbook", "leaf-engineering",
            "data-structures", "call-flows", "api-reference",
        ],
        default=[],
    )

    index = commands.add_parser("index", help="重建仓库混合索引")
    index_target = index.add_mutually_exclusive_group(required=True)
    index_target.add_argument("--repo-id")
    index_target.add_argument("--collection-id")
    index.add_argument("--profile", choices=["balanced", "quality"])

    search = commands.add_parser("search", help="在仓库或知识空间中混合检索")
    _scope_arguments(search)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=12)

    ask = commands.add_parser("ask", help="通过 opencode run 执行带引用问答")
    _scope_arguments(ask)
    ask.add_argument("question")
    ask.add_argument("--limit", type=int, default=12)

    graph = commands.add_parser("graph", help="构建、分析和检查代码知识图谱")
    graph_commands = graph.add_subparsers(dest="graph_command", required=True)
    for name, help_text in (
        ("build", "从当前运行快照重建图谱"),
        ("analyze", "重新计算社区、核心节点和桥接指标"),
        ("status", "查看分析覆盖和关系证据状态"),
    ):
        item = graph_commands.add_parser(name, help=help_text)
        item.add_argument("repository_id")
    graph_diff = graph_commands.add_parser("diff", help="比较两个运行快照的节点和关系变化")
    graph_diff.add_argument("repository_id")
    graph_diff.add_argument("from_run_id")
    graph_diff.add_argument("to_run_id")

    jobs = commands.add_parser("jobs", help="查看持久化任务")
    jobs.add_argument("--limit", type=int, default=50)
    return parser


def _repository_config_arguments(parser: argparse.ArgumentParser, require_model: bool) -> None:
    parser.add_argument("--model", required=require_model, help="OpenCode 中的 provider/model 标识")
    parser.add_argument("--agent", help="只读 OpenCode Agent，默认 clangwiki-doc")
    parser.add_argument("--opencode-executable", help="OpenCode CLI 或企业启动器")
    parser.add_argument("--analyzer-executable", help="clangwiki-analyzer 可执行文件")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--language")
    parser.add_argument("--max-source-chars-per-task", type=int)
    parser.add_argument(
        "--module-generation-concurrency", type=int,
        help="同层模块文档的 OpenCode 并发数（1-4，默认 2）",
    )
    parser.add_argument("--channel-module-path", action="append", default=[])
    parser.add_argument("--leaf-module-path", action="append", default=[])
    parser.add_argument("--embedding-profile", choices=["balanced", "quality"])


def _scope_arguments(parser: argparse.ArgumentParser) -> None:
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--repo-id")
    scope.add_argument("--collection-id")


def _config_from_args(args: argparse.Namespace) -> dict[str, Any]:
    mapping = {
        "model": "model", "agent": "agent", "opencode_executable": "opencode_executable",
        "analyzer_executable": "analyzer_executable", "timeout_seconds": "timeout_seconds",
        "language": "language", "max_source_chars_per_task": "max_source_chars_per_task",
        "module_generation_concurrency": "module_generation_concurrency",
        "embedding_profile": "embedding_profile",
    }
    values = {target: getattr(args, source) for source, target in mapping.items() if hasattr(args, source) and getattr(args, source) is not None}
    if getattr(args, "channel_module_path", None):
        values["channel_module_paths"] = list(args.channel_module_path)
    if getattr(args, "leaf_module_path", None):
        values["leaf_module_paths"] = list(args.leaf_module_path)
    return values


def _scope(args: argparse.Namespace) -> tuple[str, str]:
    if getattr(args, "repo_id", None):
        return "repository", args.repo_id
    return "collection", args.collection_id


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _legacy_generate(args: argparse.Namespace) -> dict[str, Any]:
    if not args.model:
        raise ClangWikiError("兼容模式必须通过 --model 指定 OpenCode 模型标识。")
    workspace = args.workspace.expanduser().resolve()
    config = RunConfig(
        repo=args.repo,
        workspace=workspace,
        output=(args.output or workspace / "output"),
        build_dir=(args.build_dir or workspace / "build"),
        model=args.model,
        opencode_executable=args.opencode_executable or "opencode",
        agent="clangwiki-doc" if args.agent is None else (args.agent or None),
        timeout_seconds=args.timeout_seconds or 900,
        language=args.language or "简体中文",
        max_source_chars_per_task=args.max_source_chars_per_task or 36000,
        module_generation_concurrency=normalize_module_generation_concurrency(args.module_generation_concurrency),
        overwrite=args.overwrite,
        skip_cmake=args.skip_cmake,
        skip_analysis=args.skip_analysis,
        only=tuple(args.only),
        leaf_module_paths=tuple(args.leaf_module_path),
        channel_module_paths=tuple(args.channel_module_path),
    )
    outputs = GenerationPipeline(config, args.analyzer_executable).run()
    return {"generated": [str(path) for path in outputs]}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "serve":
            data_root = args.data_root.expanduser().resolve()
            if args.repo:
                services = build_services(data_root)
                services.registry.add_repository(args.repo, config=_config_from_args(args))
            if args.host not in {"127.0.0.1", "localhost", "::1"}:
                raise ClangWikiError("本版本仅允许绑定本机地址。")
            from .server import serve

            serve(data_root=data_root, host=args.host, port=args.port)
            return 0

        if args.command == "generate" and args.repo:
            _print(_legacy_generate(args))
            return 0

        services = build_services(args.data_root.expanduser().resolve())
        if args.command == "repo":
            if args.repo_command == "add":
                _print(services.registry.add_repository(args.path, args.name, _config_from_args(args)))
            elif args.repo_command == "list":
                _print({"repositories": services.registry.list_repositories()})
            elif args.repo_command == "show":
                _print(services.registry.get_repository(args.repository_id))
            elif args.repo_command == "update":
                values: dict[str, Any] = {"config": _config_from_args(args)}
                if args.name is not None:
                    values["name"] = args.name
                _print(services.registry.update_repository(args.repository_id, values))
            elif args.repo_command == "remove":
                services.registry.remove_repository(args.repository_id, args.purge_artifacts)
                _print({"removed": args.repository_id, "source_deleted": False})
            return 0

        if args.command == "collection":
            if args.collection_command == "create":
                item = services.registry.create_collection(args.name, args.description)
                for repository_id in args.repo_id:
                    services.registry.add_collection_repository(item["id"], repository_id)
                _print(services.registry.get_collection(item["id"]))
            elif args.collection_command == "list":
                _print({"collections": services.registry.list_collections()})
            elif args.collection_command == "show":
                _print(services.registry.get_collection(args.collection_id))
            elif args.collection_command == "add":
                services.registry.add_collection_repository(args.collection_id, args.repository_id)
                _print(services.registry.get_collection(args.collection_id))
            elif args.collection_command == "remove":
                if args.delete_collection:
                    services.registry.remove_collection(args.collection_id)
                    _print({"removed": args.collection_id})
                elif args.repository_id:
                    services.registry.remove_collection_repository(args.collection_id, args.repository_id)
                    _print(services.registry.get_collection(args.collection_id))
                else:
                    raise ClangWikiError("请提供 repository_id，或使用 --delete-collection。")
            elif args.collection_command == "generate":
                _print(services.collection_generation.generate(args.collection_id, {"force": args.force}))
            elif args.collection_command == "rebuild-relations":
                _print(services.graph.rebuild_collection(args.collection_id))
            return 0

        if args.command == "generate":
            if args.collection_id:
                _print(services.collection_generation.generate(args.collection_id, {"force": args.force}))
                return 0
            overrides = _config_from_args(args)
            overrides.update({"force": args.force, "skip_cmake": args.skip_cmake, "skip_analysis": args.skip_analysis})
            if args.only:
                overrides["only"] = args.only
            _print(services.generation.generate_repository(args.repo_id, overrides))
            return 0

        if args.command == "index":
            if args.repo_id:
                _print(services.indexer.index_repository(args.repo_id, args.profile))
            else:
                _print(services.indexer.index_collection(args.collection_id, args.profile or "balanced"))
            return 0

        if args.command == "search":
            scope_type, scope_id = _scope(args)
            _print(services.indexer.search(args.query, scope_type, scope_id, args.limit))
            return 0

        if args.command == "ask":
            scope_type, scope_id = _scope(args)
            conversation = services.rag.create_conversation(scope_type, scope_id, args.question[:80])
            _print(services.rag.ask(conversation["id"], args.question, args.limit))
            return 0

        if args.command == "graph":
            repository = services.registry.get_repository(args.repository_id)
            if args.graph_command == "status":
                _print(services.graph.diagnostics(args.repository_id))
            elif args.graph_command == "analyze":
                _print(services.graph.analyze_repository(args.repository_id))
            elif args.graph_command == "diff":
                _print(services.graph.diff(args.repository_id, args.from_run_id, args.to_run_id))
            else:
                run_id = str(repository.get("active_run_id") or "")
                run = services.database.one(
                    "SELECT * FROM runs WHERE id=? AND repository_id=?", (run_id, args.repository_id),
                ) if run_id else None
                if not run:
                    raise ClangWikiError("仓库尚无成功运行快照，请先完成代码分析或 Wiki 生成。")
                _print(services.graph.ingest_repository(args.repository_id, run_id, Path(run["artifact_path"])))
            return 0

        if args.command == "jobs":
            _print({"jobs": services.jobs.list(args.limit)})
            return 0
        return 2
    except (ClangWikiError, KeyError, ValueError) as exc:
        print(f"ClangWiki 错误：{str(exc).strip(chr(39))}", file=sys.stderr)
        return 1
