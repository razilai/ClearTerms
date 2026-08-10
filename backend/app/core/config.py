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

    # Connection pool. Defaults (5 + 10 overflow) throttle concurrency too hard;
    # size the base pool to steady-state and let overflow absorb bursts.
    # pool_recycle drops connections older than this so a load balancer / server
    # idle-timeout can't leave a stale one in the pool. statement_timeout is set
    # per connection (asyncpg server_settings) as a backstop against a runaway
    # query pinning a pool slot — kept above the agent's own budget since the
    # LLM call does not hold a query open (it runs between statements).
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    db_statement_timeout_ms: int = 30000

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

    # Object storage (MinIO in dev via docker-compose; swap endpoint env vars for
    # real S3 in prod — the boto3 client is endpoint-agnostic).
    # s3_endpoint_url: backend→storage (default localhost for bare uvicorn; docker-compose
    #   overrides to http://minio:9000 so the container reaches MinIO by service name).
    # s3_public_endpoint_url: host the browser resolves presigned GET URLs against.
    s3_endpoint_url: str = "http://localhost:9000"
    s3_public_endpoint_url: str = "http://localhost:9000"
    s3_bucket: str = "clearterms-media"
    s3_access_key: str = "minioadmin"
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    s3_region: str = "us-east-1"
    media_url_ttl_seconds: int = 3600

    # Upload limits
    max_image_bytes: int = 10_000_000
    max_video_bytes: int = 100_000_000
    max_video_duration_seconds: int = 120
    max_attachments_per_item: int = 10
    video_max_height: int = 720
    image_max_dimension: int = 2048
    allowed_image_mimes: frozenset[str] = frozenset(
        {"image/jpeg", "image/png", "image/webp", "image/gif"}
    )
    allowed_video_mimes: frozenset[str] = frozenset(
        {"video/mp4", "video/webm", "video/quicktime"}
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
