from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CPPWIKI_", env_file=".env", extra="ignore"
    )

    profile: str = "production-zai-cpu"
    data_dir: Path = Path(".cppwiki")
    analyzer_path: Path = Path("bin/cpp-analyzer")
    opencode_url: str = "http://127.0.0.1:4096"
    opencode_provider: str = "zai"
    opencode_model: str = "glm-5.1"
    opencode_username: str = "opencode"
    opencode_password: Optional[str] = None
    embed_url: str = "http://127.0.0.1:11434"
    embed_model: str = "bge-m3"
    embed_num_gpu: int = 0
    embed_batch_size: int = 4
    max_context_chars: int = 60000
    request_timeout_seconds: float = 900.0

    @property
    def database_path(self) -> Path:
        return self.data_dir / "cppwiki.db"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
