from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from .database import Database, json_dumps, json_loads
from .errors import ClangWikiError
from .models import DEFAULT_MODULE_GENERATION_CONCURRENCY, normalize_module_generation_concurrency


DEFAULT_REPOSITORY_CONFIG: dict[str, Any] = {
    "model": "",
    "agent": "clangwiki-doc",
    "opencode_executable": "opencode",
    "analyzer_executable": "",
    "language": "简体中文",
    "timeout_seconds": 900,
    "max_source_chars_per_task": 36000,
    "module_generation_concurrency": DEFAULT_MODULE_GENERATION_CONCURRENCY,
    "channel_module_paths": [],
    "leaf_module_paths": [],
    "embedding_profile": "bge-m3",
}


class Registry:
    def __init__(self, database: Database) -> None:
        self.db = database

    def add_repository(
        self,
        path: Path,
        name: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        root = path.expanduser().resolve()
        if not root.is_dir():
            raise ClangWikiError(f"代码仓目录不存在：{root}")
        if not (root / "CMakeLists.txt").is_file() and not any(root.rglob("compile_commands.json")):
            raise ClangWikiError("仓库中未发现 CMakeLists.txt 或 compile_commands.json。")
        existing = self.db.one("SELECT * FROM repositories WHERE path = ?", (str(root),))
        if existing:
            return self._repository(existing)
        repository_id = self._stable_id("repo", str(root).casefold())
        now = time.time()
        branch, commit = git_identity(root)
        # The platform default is intentionally stored outside individual
        # repositories: it lets an administrator change the preferred
        # OpenCode model without exposing, copying, or parsing credentials.
        # An explicit repository model still always wins.
        default_model_row = self.db.one("SELECT value_json FROM settings WHERE key = ?", ("default_model",))
        default_model = json_loads(default_model_row["value_json"], "") if default_model_row else ""
        default_embedding_row = self.db.one(
            "SELECT value_json FROM settings WHERE key = ?", ("default_embedding_profile",)
        )
        default_embedding = json_loads(default_embedding_row["value_json"], "") if default_embedding_row else ""
        inherited = {}
        if default_model:
            inherited["model"] = default_model
        if default_embedding:
            inherited["embedding_profile"] = default_embedding
        merged = {**DEFAULT_REPOSITORY_CONFIG, **inherited, **(config or {})}
        _validate_repository_config(merged)
        self.db.execute(
            "INSERT INTO repositories(id,name,path,config_json,status,git_branch,git_commit,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (repository_id, name or root.name, str(root), json_dumps(merged), "registered", branch, commit, now, now),
        )
        workspace = self.repository_root(repository_id)
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "runs").mkdir(exist_ok=True)
        (workspace / "index").mkdir(exist_ok=True)
        self._write_repository_manifest(repository_id)
        return self.get_repository(repository_id)

    def list_repositories(self) -> list[dict[str, Any]]:
        return [self._repository(row) for row in self.db.all("SELECT * FROM repositories ORDER BY name")]

    def get_repository(self, repository_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM repositories WHERE id = ?", (repository_id,))
        if not row:
            raise KeyError(f"仓库不存在：{repository_id}")
        return self._repository(row)

    def update_repository(self, repository_id: str, values: dict[str, Any]) -> dict[str, Any]:
        current = self.get_repository(repository_id)
        config = dict(current["config"])
        if isinstance(values.get("config"), dict):
            config.update(values["config"])
        _validate_repository_config(config)
        name = str(values.get("name") or current["name"]).strip()
        self.db.execute(
            "UPDATE repositories SET name=?, config_json=?, updated_at=? WHERE id=?",
            (name, json_dumps(config), time.time(), repository_id),
        )
        self._write_repository_manifest(repository_id)
        return self.get_repository(repository_id)

    def remove_repository(self, repository_id: str, purge_artifacts: bool = False) -> None:
        self.get_repository(repository_id)
        self.db.execute("DELETE FROM repositories WHERE id = ?", (repository_id,))
        if purge_artifacts:
            target = self.repository_root(repository_id)
            expected_parent = (self.db.data_root / "repositories").resolve()
            if target.resolve().parent == expected_parent and target.is_dir():
                shutil.rmtree(target)

    def create_collection(self, name: str, description: str = "", config: dict[str, Any] | None = None) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name:
            raise ClangWikiError("知识空间名称不能为空。")
        collection_id = f"col-{uuid.uuid4().hex[:12]}"
        now = time.time()
        self.db.execute(
            "INSERT INTO collections(id,name,description,config_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (collection_id, clean_name, description.strip(), json_dumps(config or {}), now, now),
        )
        (self.db.data_root / "collections" / collection_id / "output").mkdir(parents=True, exist_ok=True)
        return self.get_collection(collection_id)

    def list_collections(self) -> list[dict[str, Any]]:
        return [self._collection(row) for row in self.db.all("SELECT * FROM collections ORDER BY name")]

    def get_collection(self, collection_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM collections WHERE id=?", (collection_id,))
        if not row:
            raise KeyError(f"知识空间不存在：{collection_id}")
        return self._collection(row)

    def update_collection(self, collection_id: str, values: dict[str, Any]) -> dict[str, Any]:
        current = self.get_collection(collection_id)
        config = dict(current["config"])
        if isinstance(values.get("config"), dict):
            config.update(values["config"])
        self.db.execute(
            "UPDATE collections SET name=?,description=?,config_json=?,updated_at=? WHERE id=?",
            (
                str(values.get("name") or current["name"]).strip(),
                str(values.get("description", current["description"])).strip(),
                json_dumps(config),
                time.time(),
                collection_id,
            ),
        )
        return self.get_collection(collection_id)

    def remove_collection(self, collection_id: str) -> None:
        self.get_collection(collection_id)
        self.db.execute("DELETE FROM collections WHERE id=?", (collection_id,))

    def add_collection_repository(self, collection_id: str, repository_id: str) -> dict[str, Any]:
        self.get_collection(collection_id)
        self.get_repository(repository_id)
        self.db.execute(
            "INSERT OR IGNORE INTO collection_repositories(collection_id,repository_id,added_at) VALUES(?,?,?)",
            (collection_id, repository_id, time.time()),
        )
        return self.get_collection(collection_id)

    def remove_collection_repository(self, collection_id: str, repository_id: str) -> dict[str, Any]:
        self.db.execute(
            "DELETE FROM collection_repositories WHERE collection_id=? AND repository_id=?",
            (collection_id, repository_id),
        )
        return self.get_collection(collection_id)

    def collection_repository_ids(self, collection_id: str) -> list[str]:
        self.get_collection(collection_id)
        return [
            row["repository_id"]
            for row in self.db.all(
                "SELECT repository_id FROM collection_repositories WHERE collection_id=? ORDER BY added_at",
                (collection_id,),
            )
        ]

    def repository_root(self, repository_id: str) -> Path:
        return self.db.data_root / "repositories" / repository_id

    def run_root(self, repository_id: str, run_id: str) -> Path:
        return self.repository_root(repository_id) / "runs" / run_id

    def collection_root(self, collection_id: str) -> Path:
        return self.db.data_root / "collections" / collection_id

    def _repository(self, row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row["config"] = json_loads(row.pop("config_json"), {})
        run = None
        if row.get("active_run_id"):
            run = self.db.one("SELECT * FROM runs WHERE id=?", (row["active_run_id"],))
        row["active_run"] = self._run(run) if run else None
        row["workspace"] = str(self.repository_root(row["id"]))
        return row

    def _collection(self, row: dict[str, Any]) -> dict[str, Any]:
        row = dict(row)
        row["config"] = json_loads(row.pop("config_json"), {})
        ids = self.collection_repository_ids_without_validation(row["id"])
        row["repository_ids"] = ids
        row["repositories"] = [self.get_repository(item) for item in ids]
        return row

    def collection_repository_ids_without_validation(self, collection_id: str) -> list[str]:
        return [
            item["repository_id"]
            for item in self.db.all(
                "SELECT repository_id FROM collection_repositories WHERE collection_id=? ORDER BY added_at",
                (collection_id,),
            )
        ]

    @staticmethod
    def _run(row: dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        result["manifest"] = json_loads(result.pop("manifest_json"), {})
        return result

    def _write_repository_manifest(self, repository_id: str) -> None:
        repository = self.get_repository(repository_id)
        payload = {
            "id": repository["id"],
            "name": repository["name"],
            "path": repository["path"],
            "config": repository["config"],
        }
        target = self.repository_root(repository_id) / "repository.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json_dumps(payload) + "\n", encoding="utf-8")

    @staticmethod
    def _stable_id(prefix: str, value: str) -> str:
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
        return f"{prefix}-{digest}"


def _validate_repository_config(config: dict[str, Any]) -> None:
    # Canonicalise string values from JSON/HTTP payloads before persisting them.
    config["module_generation_concurrency"] = normalize_module_generation_concurrency(
        config.get("module_generation_concurrency", DEFAULT_MODULE_GENERATION_CONCURRENCY)
    )


def git_identity(root: Path) -> tuple[str | None, str | None]:
    if not (root / ".git").exists():
        return None, None
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

    def run(*args: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", "-C", str(root), *args], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=10, check=False,
                creationflags=flags,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        value = result.stdout.strip()
        return value if result.returncode == 0 and value else None

    return run("branch", "--show-current"), run("rev-parse", "HEAD")
