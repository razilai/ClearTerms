"""Application settings, loaded from environment / .env via pydantic-settings."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLEARTERMS_")

    # Dev default; set CLEARTERMS_DATABASE_URL in production. Must be an async
    # driver URL (asyncpg) — the engine and Alembic env both run async.
    database_url: str = (
        "postgresql+asyncpg://clearterms:clearterms@localhost:5432/clearterms"
    )

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


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
