"""Application settings, loaded from environment / .env via pydantic-settings."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLEARTERMS_")

    database_url: str = "sqlite+aiosqlite:///./data/clearterms.db"

    # Dev-only default; set CLEARTERMS_JWT_SECRET (>=32 bytes) in production.
    jwt_secret: SecretStr = SecretStr("change-me")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24

    ollama_base_url: str = "http://localhost:11434"
    agent_model: str = "qwen3:4b"
    # Bump on model/prompt changes to invalidate cached analyses. Must track
    # agent_model: overriding the model without bumping this writes scores from
    # one model into cache entries another model's scores are served from.
    model_version: str = "qwen3-4b-v1"

    max_analyze_bytes: int = 1_000_000
    chunk_tokens: int = 3000
    chunk_overlap_tokens: int = 200

    # Concurrent analyses. One LLM generation already saturates a laptop CPU;
    # raise only when the GPU VM can serve more than one at a time.
    analysis_workers: int = 1
    # Waiting jobs allowed before /analyze sheds load with a 503. Sized so a
    # queued caller's wait stays bounded by maxsize x per-job time.
    analysis_queue_maxsize: int = 100
    # How long a caller waits for its turn before giving up with a 504. The job
    # itself is NOT cancelled — it keeps running and still populates the cache.
    analysis_queue_timeout_seconds: float = 300.0


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
