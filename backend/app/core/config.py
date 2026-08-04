"""Application settings, loaded from environment / .env via pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLEARTERMS_")

    database_url: str = "sqlite+aiosqlite:///./data/clearterms.db"

    jwt_secret: str = "change-me"
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
