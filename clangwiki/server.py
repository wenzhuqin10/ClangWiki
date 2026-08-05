from __future__ import annotations

"""A small, dependency-free local web workspace for ClangWiki.

The server is intentionally local-first: it reads ClangWiki artifacts, starts the
existing synchronous pipeline in a worker thread, and delegates model access to
the already authenticated ``opencode run`` executable. It never accepts or stores
an API key and it does not start OpenCode Server.
"""

import json
import mimetypes
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, replace
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .errors import GenerationCancelled
from .io import read_json
from .models import RunConfig
from .pipeline import GenerationPipeline


@dataclass
class Job:
    job_id: str
    status: str = "queued"
    created_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None
    progress: int = 0
    stage: str = "queued"
    message: str = "Queued"
    outputs: list[str] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.cancel_event = threading.Event()
        self.condition = threading.Condition()

    def emit(self, event: dict[str, Any]) -> None:
        with self.condition:
            self.stage = str(event.get("stage", self.stage))
            self.message = str(event.get("message", self.message))
            value = event.get("progress")
            if isinstance(value, int):
                self.progress = max(0, min(100, value))
            payload = {
                "type": "progress",
                "stage": self.stage,
                "message": self.message,
                "progress": self.progress,
                "time": time.time(),
            }
            self.events.append(payload)
            self.condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": self.progress,
            "stage": self.stage,
            "message": self.message,
            "outputs": self.outputs or [],
            "error": self.error,
        }


class JobManager:
    def __init__(self, config: RunConfig, analyzer_executable: str | None) -> None:
        self.config = config
        self.analyzer_executable = analyzer_executable
        self.jobs: dict[str, Job] = {}
        self.lock = threading.Lock()

    def start(self, overrides: dict[str, Any] | None = None) -> Job:
        with self.lock:
            active = [job for job in self.jobs.values() if job.status in {"queued", "running"}]
            if active:
                raise RuntimeError("A generation is already running")
            cfg = self._override_config(overrides or {})
            job = Job(uuid.uuid4().hex[:12], created_at=time.time())
            self.jobs[job.job_id] = job
        thread = threading.Thread(target=self._run, args=(job, cfg), daemon=True)
        thread.start()
        return job

    def _override_config(self, values: dict[str, Any]) -> RunConfig:
        allowed = {
            "model", "agent", "opencode_executable", "timeout_seconds", "language",
            "max_source_chars_per_task", "overwrite", "skip_cmake", "skip_analysis",
            "only", "leaf_module_paths", "channel_module_paths",
        }
        patch: dict[str, Any] = {key: value for key, value in values.items() if key in allowed}
        for key in ("only", "leaf_module_paths", "channel_module_paths"):
            if key in patch and isinstance(patch[key], list):
                patch[key] = tuple(str(item) for item in patch[key])
        return replace(self.config, **patch)

    def _run(self, job: Job, config: RunConfig) -> None:
        job.status = "running"
        job.started_at = time.time()
        job.emit({"stage": "start", "message": "Starting ClangWiki generation", "progress": 0})
        try:
            outputs = GenerationPipeline(
                config,
                self.analyzer_executable,
                progress_sink=job.emit,
                cancel_event=job.cancel_event,
            ).run()
            with job.condition:
                job.status = "cancelled" if job.cancel_event.is_set() else "completed"
                job.outputs = [str(path) for path in outputs]
                job.finished_at = time.time()
                job.condition.notify_all()
        except GenerationCancelled:
            with job.condition:
                job.status = "cancelled"
                job.message = "Generation cancelled"
                job.finished_at = time.time()
                job.condition.notify_all()
        except Exception as exc:  # surfaced through the UI and server logs
            with job.condition:
                job.status = "failed"
                job.error = str(exc)
                job.message = "Generation failed"
                job.finished_at = time.time()
                job.condition.notify_all()
            traceback.print_exc()

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            return [job.snapshot() for job in self.jobs.values()]


class ClangWikiHandler(BaseHTTPRequestHandler):
    server_version = "ClangWikiLocal/0.1"

    @property
    def app(self) -> "ClangWikiServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[clangwiki-web] {self.address_string()} - {fmt % args}")

    def _send(self, status: int, payload: Any, content_type: str = "application/json; charset=utf-8") -> None:
        raw = payload if isinstance(payload, bytes) else (
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if content_type.startswith("application/json") else str(payload).encode("utf-8")
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path.startswith("/api/"):
                self._api_get(parsed.path, parse_qs(parsed.query))
            else:
                self._static(parsed.path)
        except Exception as exc:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/generate":
                job = self.app.jobs.start(self._body())
                self._send(HTTPStatus.ACCEPTED, job.snapshot())
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/cancel"):
                job_id = parsed.path.split("/")[3]
                job = self.app.jobs.get(job_id)
                if job is None:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "job not found"})
                    return
                job.cancel_event.set()
                job.emit({"stage": "cancel", "message": "Cancellation requested", "progress": job.progress})
                self._send(HTTPStatus.OK, job.snapshot())
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})
        except RuntimeError as exc:
            self._send(HTTPStatus.CONFLICT, {"error": str(exc)})
        except Exception as exc:
            self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _api_get(self, path: str, query: dict[str, list[str]]) -> None:
        if path == "/api/status":
            self._send(HTTPStatus.OK, self.app.status())
        elif path == "/api/tree":
            self._send(HTTPStatus.OK, self.app.tree())
        elif path == "/api/relations":
            self._send(HTTPStatus.OK, self.app.relations())
        elif path == "/api/documents":
            self._send(HTTPStatus.OK, self.app.documents())
        elif path == "/api/document":
            relative = unquote((query.get("path") or [""])[0])
            self._send(HTTPStatus.OK, self.app.document(relative))
        elif path == "/api/jobs":
            self._send(HTTPStatus.OK, {"jobs": self.app.jobs.list()})
        elif path.startswith("/api/jobs/") and path.endswith("/events"):
            self._events(path.split("/")[3])
        elif path.startswith("/api/jobs/"):
            job = self.app.jobs.get(path.split("/")[3])
            if job is None:
                self._send(HTTPStatus.NOT_FOUND, {"error": "job not found"})
            else:
                self._send(HTTPStatus.OK, job.snapshot())
        else:
            self._send(HTTPStatus.NOT_FOUND, {"error": "unknown endpoint"})

    def _events(self, job_id: str) -> None:
        job = self.app.jobs.get(job_id)
        if job is None:
            self._send(HTTPStatus.NOT_FOUND, {"error": "job not found"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        cursor = 0
        while True:
            with job.condition:
                while cursor >= len(job.events) and job.status in {"queued", "running"}:
                    job.condition.wait(timeout=1.0)
                events = job.events[cursor:]
                cursor = len(job.events)
                status = job.status
            for event in events:
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
            if status not in {"queued", "running"}:
                final = {"type": "complete", **job.snapshot()}
                self.wfile.write(f"data: {json.dumps(final, ensure_ascii=False)}\n\n".encode("utf-8"))
                self.wfile.flush()
                break

    def _static(self, path: str) -> None:
        relative = unquote(path.lstrip("/")) or "index.html"
        if relative.startswith("api/") or ".." in Path(relative).parts:
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        target = (self.app.web_root / relative).resolve()
        if self.app.web_root.resolve() not in target.parents and target != self.app.web_root.resolve():
            self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        if not target.is_file():
            target = self.app.web_root / "index.html"
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send(HTTPStatus.OK, target.read_bytes(), f"{content_type}; charset=utf-8")


class ClangWikiServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], config: RunConfig, analyzer_executable: str | None) -> None:
        super().__init__(address, ClangWikiHandler)
        self.config = config
        self.jobs = JobManager(config, analyzer_executable)
        self.web_root = Path(__file__).resolve().parent / "web"

    def status(self) -> dict[str, Any]:
        workspace = self.config.workspace.expanduser().resolve()
        knowledge = workspace / "knowledge"
        analysis = workspace / "analysis"
        diagnostics = _read_json(analysis / "diagnostics.json", {})
        return {
            "version": __version__,
            "repo": str(self.config.repo.expanduser().resolve()),
            "workspace": str(workspace),
            "output": str(self.config.output.expanduser().resolve()),
            "model": self.config.model,
            "agent": self.config.agent,
            "opencode_executable": self.config.opencode_executable,
            "analysis_mode": diagnostics.get("mode", "not-run"),
            "diagnostics": diagnostics.get("diagnostics", []),
            "artifacts": {
                "module_tree": (knowledge / "module_tree.json").is_file(),
                "relations": (knowledge / "relations.json").is_file(),
                "documents": self.config.output.is_dir(),
            },
        }

    def tree(self) -> dict[str, Any]:
        knowledge = self.config.workspace.expanduser().resolve() / "knowledge"
        return {
            "tree": _read_json(knowledge / "module_tree.json", {"roots": [], "nodes": {}}),
            "modules": _read_json(knowledge / "modules.json", []),
        }

    def relations(self) -> dict[str, Any]:
        path = self.config.workspace.expanduser().resolve() / "knowledge" / "relations.json"
        values = _read_json(path, [])
        return {"relations": values if isinstance(values, list) else []}

    def documents(self) -> dict[str, Any]:
        root = self.config.output.expanduser().resolve()
        if not root.is_dir():
            return {"documents": []}
        documents = []
        for path in sorted(root.rglob("*.md")):
            relative = path.relative_to(root).as_posix()
            first_heading = next((line[2:].strip() for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.startswith("# ")), relative)
            documents.append({"path": relative, "title": first_heading, "size": path.stat().st_size})
        return {"documents": documents}

    def document(self, relative: str) -> dict[str, Any]:
        root = self.config.output.expanduser().resolve()
        target = (root / relative).resolve()
        if root not in target.parents or not target.is_file() or target.suffix.lower() != ".md":
            raise FileNotFoundError("document not found")
        return {"path": target.relative_to(root).as_posix(), "content": target.read_text(encoding="utf-8", errors="replace")}


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        return read_json(path)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return fallback


def serve(config: RunConfig, analyzer_executable: str | None, host: str, port: int) -> None:
    server = ClangWikiServer((host, port), config, analyzer_executable)
    print(f"ClangWiki UI: http://{host}:{port}/")
    print(f"Repository: {config.repo}")
    print("Press Ctrl+C to stop the local server.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ClangWiki UI")
    finally:
        server.server_close()
