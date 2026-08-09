from __future__ import annotations

from pathlib import Path


def serve(data_root: Path, host: str = "127.0.0.1", port: int = 8082) -> None:
    """Start the same-origin local FastAPI workspace."""
    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - installation error path
        raise RuntimeError("缺少 FastAPI 运行依赖，请重新安装 ClangWiki。") from exc

    from .api import create_app

    app = create_app(data_root)
    print(f"ClangWiki UI: http://{host}:{port}/")
    print(f"Data root: {data_root.expanduser().resolve()}")
    print("Press Ctrl+C to stop the local server.")
    uvicorn.run(app, host=host, port=port, log_level="info")
