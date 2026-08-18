"""Application settings, loaded from environment / .env via pydantic-settings."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The dev-only JWT secret the guard below refuses to boot on outside dev.
_DEV_JWT_SECRET = "change-me"
_MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CLEARTERMS_")

    # Deployment mode. "dev" keeps the convenience defaults (dev JWT secret) usable;
    # anything else is treated as a real deployment and hardens startup — see the
    # validator below. Set CLEARTERMS_ENVIRONMENT=prod in production.
    environment: Literal["dev", "prod"] = "dev"

    # Root log level; logs are emitted as JSON (see core/logging.py).
    log_level: str = "INFO"

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
    agent_model: str = "gemma3:4b"
    # Bump on model/prompt changes to invalidate cached analyses. Must track
    # agent_model: overriding the model without bumping this writes scores from
    # one model into cache entries another model's scores are served from.
    model_version: str = "gemma3-4b-v1"

    max_analyze_bytes: int = 1_000_000
    chunk_tokens: int = 3000
    chunk_overlap_tokens: int = 200

    # Input length caps, in characters. The schemas are the enforcement point;
    # frontend/src/lib/limits.ts hand-mirrors these for input UX only (a client
    # cap is a courtesy, not a control — curl bypasses it). The analyze paste
    # box has no entry here: it is bounded by max_analyze_bytes above.
    max_email_chars: int = 254  # RFC 5321 addr-spec ceiling
    # Argon2 hashes the whole input, so an uncapped password is a CPU-burn
    # vector. NIST SP 800-63B asks for >=64 accepted; 128 clears that.
    max_password_chars: int = 128
    max_post_title_chars: int = 255  # mirrors Post.title's VARCHAR(255)
    max_post_body_chars: int = 10_000
    max_comment_body_chars: int = 5_000
    max_message_body_chars: int = 5_000
    max_url_chars: int = 2_048  # de-facto browser/CDN URL ceiling

    # Concurrent analyses. One LLM generation already saturates a laptop CPU;
    # raise only when the GPU VM can serve more than one at a time.
    analysis_workers: int = 1
    # Waiting jobs allowed before /analyze sheds load with a 503. Sized so a
    # queued caller's wait stays bounded by maxsize x per-job time.
    analysis_queue_maxsize: int = 100
    # How long a caller waits for a *result* before giving up with a 504. Not
    # just queue time: the wait wraps the whole submit, so this bounds time
    # queued plus time running. The job itself is NOT cancelled — it keeps
    # running and still populates the cache.
    analysis_queue_timeout_seconds: float = 300.0
    # Fairness dial. A queued job's score is priority * this + sequence, so at
    # most `priority * alpha` later arrivals can overtake it — that bound is
    # what keeps a busy user's later jobs from starving. Read it as "how many
    # other users' first jobs may jump ahead of your second job". Too low and
    # priority stops meaning anything; too high (near analysis_queue_maxsize)
    # and a second job is unreachable while the queue is busy.
    analysis_queue_alpha: int = 10

    # Rate limiting (fixed-window, backed by the rate_limits table). login is
    # keyed per client IP (no user yet — throttles credential brute-force);
    # analyze is keyed per user (throttles expensive LLM calls / cost). A window
    # is a fixed slice of wall-clock time; up to `limit` requests are allowed per
    # window per key. sweep_interval is how often expired counter rows are purged.
    rate_limit_login_max: int = 10
    rate_limit_login_window_seconds: int = 300
    rate_limit_analyze_max: int = 20
    rate_limit_analyze_window_seconds: int = 3600
    rate_limit_sweep_interval_seconds: int = 600

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

    @model_validator(mode="after")
    def _guard_prod_secrets(self) -> "Settings":
        """Refuse to boot a real deployment on the dev JWT secret.

        The dev default is trivially forgeable, so a prod process that starts on
        it is a silent full-auth-bypass. Gate on environment so dev/tests keep
        the convenient default while any non-dev deploy must supply a real secret
        (>=32 bytes) via CLEARTERMS_JWT_SECRET.
        """
        if self.environment == "dev":
            return self
        secret = self.jwt_secret.get_secret_value()
        if secret == _DEV_JWT_SECRET:
            raise ValueError(
                "CLEARTERMS_JWT_SECRET is still the dev default; set a real secret "
                f"(>={_MIN_JWT_SECRET_BYTES} bytes) when CLEARTERMS_ENVIRONMENT is not 'dev'."
            )
        if len(secret.encode()) < _MIN_JWT_SECRET_BYTES:
            raise ValueError(
                f"CLEARTERMS_JWT_SECRET must be >={_MIN_JWT_SECRET_BYTES} bytes."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
