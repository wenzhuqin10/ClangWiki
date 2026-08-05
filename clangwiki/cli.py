from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .errors import ClangWikiError
from .models import RunConfig
from .pipeline import GenerationPipeline


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="clangwiki", description="C/C++ repository documentation through Clang and OpenCode CLI")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate", help="generate a Markdown Wiki")
    generate.add_argument("--repo", required=True, type=Path, help="target C/C++ repository root")
    generate.add_argument("--workspace", type=Path, default=Path("workspace"), help="external intermediate artifact directory")
    generate.add_argument("--output", type=Path, help="Markdown output directory (default: <workspace>/output)")
    generate.add_argument("--build-dir", type=Path, help="CMake configure directory (default: <workspace>/build)")
    generate.add_argument("--model", required=True, help="exact OpenCode provider/model identifier")
    generate.add_argument("--agent", default="clangwiki-doc", help="installed read-only OpenCode agent; use empty string to omit")
    generate.add_argument("--opencode-executable", default="opencode", help="OpenCode CLI or compatible enterprise launcher, e.g. nga")
    generate.add_argument("--analyzer-executable", help="built clangwiki-analyzer path; fallback is explicitly labelled partial")
    generate.add_argument("--timeout-seconds", type=int, default=900)
    generate.add_argument("--language", default="简体中文")
    generate.add_argument("--max-source-chars-per-task", type=int, default=36000)
    generate.add_argument(
        "--channel-module-path",
        action="append",
        default=[],
        help=(
            "repository-relative channel directory whose immediate source subdirectories become leaves; "
            "repeat for channels such as src/phy/pdsch and src/phy/pusch"
        ),
    )
    generate.add_argument(
        "--leaf-module-path",
        action="append",
        default=[],
        help=(
            "advanced override: repository-relative directory treated directly as a leaf boundary; "
            "do not combine with --channel-module-path"
        ),
    )
    generate.add_argument("--overwrite", action="store_true")
    generate.add_argument("--skip-cmake", action="store_true")
    generate.add_argument("--skip-analysis", action="store_true")
    generate.add_argument("--only", action="append", choices=["readme", "architecture", "module", "data-structures", "call-flows", "api-reference"], default=[])
    serve = commands.add_parser("serve", help="start the local ClangWiki visual workspace")
    serve.add_argument("--repo", required=True, type=Path, help="target C/C++ repository root")
    serve.add_argument("--workspace", type=Path, default=Path("workspace"), help="external intermediate artifact directory")
    serve.add_argument("--output", type=Path, help="Markdown output directory (default: <workspace>/output)")
    serve.add_argument("--build-dir", type=Path, help="CMake configure directory (default: <workspace>/build)")
    serve.add_argument("--model", required=True, help="exact OpenCode provider/model identifier")
    serve.add_argument("--agent", default="clangwiki-doc", help="read-only OpenCode agent; use empty string to omit")
    serve.add_argument("--opencode-executable", default="opencode", help="OpenCode CLI or compatible enterprise launcher")
    serve.add_argument("--analyzer-executable", help="built clangwiki-analyzer path")
    serve.add_argument("--timeout-seconds", type=int, default=900)
    serve.add_argument("--language", default="简体中文")
    serve.add_argument("--max-source-chars-per-task", type=int, default=36000)
    serve.add_argument("--channel-module-path", action="append", default=[])
    serve.add_argument("--leaf-module-path", action="append", default=[])
    serve.add_argument("--overwrite", action="store_true")
    serve.add_argument("--skip-cmake", action="store_true")
    serve.add_argument("--skip-analysis", action="store_true")
    serve.add_argument("--host", default="127.0.0.1", help="bind address; localhost is recommended")
    serve.add_argument("--port", type=int, default=8081)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        from .server import serve as run_server

        workspace = args.workspace.expanduser().resolve()
        config = RunConfig(
            repo=args.repo, workspace=workspace, output=(args.output or workspace / "output"),
            build_dir=(args.build_dir or workspace / "build"), model=args.model,
            opencode_executable=args.opencode_executable, agent=args.agent or None,
            timeout_seconds=args.timeout_seconds, language=args.language,
            max_source_chars_per_task=args.max_source_chars_per_task, overwrite=args.overwrite,
            skip_cmake=args.skip_cmake, skip_analysis=args.skip_analysis,
            leaf_module_paths=tuple(args.leaf_module_path),
            channel_module_paths=tuple(args.channel_module_path),
        )
        run_server(config, args.analyzer_executable, args.host, args.port)
        return 0
    if args.command != "generate":
        return 2
    workspace = args.workspace.expanduser().resolve()
    config = RunConfig(
        repo=args.repo, workspace=workspace, output=(args.output or workspace / "output"),
        build_dir=(args.build_dir or workspace / "build"), model=args.model,
        opencode_executable=args.opencode_executable, agent=args.agent or None,
        timeout_seconds=args.timeout_seconds, language=args.language,
        max_source_chars_per_task=args.max_source_chars_per_task, overwrite=args.overwrite,
        skip_cmake=args.skip_cmake, skip_analysis=args.skip_analysis, only=tuple(args.only),
        leaf_module_paths=tuple(args.leaf_module_path),
        channel_module_paths=tuple(args.channel_module_path),
    )
    try:
        outputs = GenerationPipeline(config, args.analyzer_executable).run()
    except ClangWikiError as exc:
        print(f"ClangWiki error: {exc}", file=sys.stderr)
        return 1
    print("Generated:")
    for output in outputs:
        print(output)
    return 0
