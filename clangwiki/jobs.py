from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .database import Database, json_dumps, json_loads


JobHandler = Callable[[str, dict[str, Any], Callable[[dict[str, object]], None], threading.Event], Any]


class PersistentJobManager:
    """SQLite-backed local job queue with one model lane and one CPU lane."""

    MODEL_KINDS = {"generate", "collection_generate", "ask"}

    def __init__(self, database: Database) -> None:
        self.db = database
        self.handlers: dict[str, JobHandler] = {}
        self.model_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clangwiki-model")
        self.cpu_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clangwiki-cpu")
        self.cancel_events: dict[str, threading.Event] = {}
        self.lock = threading.Lock()
        now = time.time()
        self.db.execute(
            "UPDATE jobs SET status='interrupted',stage='interrupted',message='服务重启导致任务中断',finished_at=? "
            "WHERE status IN ('queued','running')",
            (now,),
        )

    def register(self, kind: str, handler: JobHandler) -> None:
        self.handlers[kind] = handler

    def start(self, kind: str, scope_type: str, scope_id: str | None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if kind not in self.handlers:
            raise ValueError(f"未注册任务类型：{kind}")
        if scope_id and self.db.one(
            "SELECT id FROM jobs WHERE scope_type=? AND scope_id=? AND status IN ('queued','running')",
            (scope_type, scope_id),
        ):
            raise RuntimeError("该仓库或知识空间已有写入任务正在排队或运行。")
        job_id = f"job-{uuid.uuid4().hex[:16]}"
        now = time.time()
        self.db.execute(
            "INSERT INTO jobs(id,kind,scope_type,scope_id,status,stage,progress,message,payload_json,result_json,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (job_id, kind, scope_type, scope_id, "queued", "queued", 0, "任务已进入队列", json_dumps(payload or {}), "{}", now),
        )
        cancel = threading.Event()
        with self.lock:
            self.cancel_events[job_id] = cancel
        executor = self.model_executor if kind in self.MODEL_KINDS else self.cpu_executor
        executor.submit(self._run, job_id, kind, scope_id or "", payload or {}, cancel)
        return self.get(job_id)

    def _run(self, job_id: str, kind: str, scope_id: str, payload: dict[str, Any], cancel: threading.Event) -> None:
        self._update(job_id, status="running", stage="start", message="任务开始执行", progress=0, started_at=time.time())

        def emit(event: dict[str, object]) -> None:
            self.emit(job_id, event)

        try:
            result = self.handlers[kind](scope_id, payload, emit, cancel)
            status = "cancelled" if cancel.is_set() else "completed"
            self._update(
                job_id, status=status, stage=status,
                message="任务已取消" if status == "cancelled" else "任务执行完成",
                progress=100, result_json=json_dumps(result), finished_at=time.time(),
            )
        except Exception as exc:
            error = _failure_detail(exc)
            self._update(
                job_id, status="failed", stage="failed", message="任务执行失败：" + _one_line(str(exc)),
                error=error, finished_at=time.time(),
            )
            self.emit(job_id, {
                "stage": "failed", "message": "生成失败：" + _one_line(str(exc)),
                "progress": self.get(job_id)["progress"], "error": error,
            })
            traceback.print_exc()
        finally:
            with self.lock:
                self.cancel_events.pop(job_id, None)

    def emit(self, job_id: str, event: dict[str, object]) -> None:
        current = self.get(job_id)
        progress = event.get("progress")
        value = current["progress"] if not isinstance(progress, int) else max(0, min(100, progress))
        stage = str(event.get("stage") or current["stage"])
        message = str(event.get("message") or current["message"])
        payload = {"type": "progress", "job_id": job_id, "stage": stage, "message": message, "progress": value, "time": time.time()}
        with self.db.transaction() as connection:
            connection.execute("UPDATE jobs SET stage=?,message=?,progress=? WHERE id=?", (stage, message, value, job_id))
            connection.execute("INSERT INTO job_events(job_id,event_json,created_at) VALUES(?,?,?)", (job_id, json_dumps(payload), time.time()))

    def cancel(self, job_id: str) -> dict[str, Any]:
        self.get(job_id)
        with self.lock:
            event = self.cancel_events.get(job_id)
        if event:
            event.set()
            self.emit(job_id, {"stage": "cancel", "message": "已请求取消，正在等待当前步骤安全退出"})
        return self.get(job_id)

    def retry(self, job_id: str) -> dict[str, Any]:
        current = self.get(job_id)
        if current["status"] not in {"failed", "cancelled", "interrupted"}:
            raise ValueError("只有失败、取消或中断的任务可以重试。")
        return self.start(current["kind"], current["scope_type"], current.get("scope_id"), current["payload"])

    def get(self, job_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not row:
            raise KeyError("任务不存在")
        return self._public(row)

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        return [self._public(row) for row in self.db.all("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))]

    def events(self, job_id: str, after: int = 0) -> list[dict[str, Any]]:
        self.get(job_id)
        return [
            {"event_id": row["id"], **json_loads(row["event_json"], {})}
            for row in self.db.all("SELECT * FROM job_events WHERE job_id=? AND id>? ORDER BY id", (job_id, after))
        ]

    def _update(self, job_id: str, **values: Any) -> None:
        allowed = {"status", "stage", "message", "progress", "result_json", "error", "started_at", "finished_at"}
        clean = {key: value for key, value in values.items() if key in allowed}
        if not clean:
            return
        assignments = ",".join(f"{key}=?" for key in clean)
        self.db.execute(f"UPDATE jobs SET {assignments} WHERE id=?", tuple(clean.values()) + (job_id,))
        snapshot = self.get(job_id)
        payload = {"type": "status", **snapshot, "time": time.time()}
        self.db.execute(
            "INSERT INTO job_events(job_id,event_json,created_at) VALUES(?,?,?)",
            (job_id, json_dumps(payload), time.time()),
        )

    @staticmethod
    def _public(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = json_loads(result.pop("payload_json"), {})
        result["result"] = json_loads(result.pop("result_json"), {})
        return result


def _one_line(value: str, limit: int = 360) -> str:
    value = " ".join(value.split())
    return value[:limit] + ("…" if len(value) > limit else "")


def _failure_detail(exc: Exception) -> str:
    """Keep a useful failure explanation without exposing a full server traceback."""
    detail = str(exc).strip() or repr(exc)
    return f"错误类型：{type(exc).__name__}\n\n{detail[:6000]}"
