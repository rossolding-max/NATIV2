"""Application settings. Loads from environment / .env per `docs/configuration.md`.

Single source of truth — never read ``os.environ`` in domain code. Inject
``Settings`` (or ``settings``) from this module.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import (
    AnyHttpUrl,
    Field,
    SecretStr,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Loads env vars / .env values; refuses to start with unsafe defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── App identity ─────────────────────────────────────────────────
    nativ2_environment: Literal["development", "test", "production"] = "development"
    nativ2_version: str = "0.1.0"

    # ── FastAPI bind ─────────────────────────────────────────────────
    # `nativ2_bind_host` carried as a string (not IPvAnyAddress) — we only
    # ever compare it to "127.0.0.1"; the model_validator below enforces the
    # external-bind safety check.
    nativ2_bind_host: str = "127.0.0.1"
    nativ2_bind_port: int = Field(default=8000, ge=1, le=65535)
    nativ2_external_bind_confirmed: bool = False
    nativ2_api_workers: int = Field(default=1, ge=1, le=16)

    # ── Postgres ─────────────────────────────────────────────────────
    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "nativ2"
    postgres_user: str = "nativ2"
    postgres_password: SecretStr  # REQUIRED
    postgres_pool_size: int = Field(default=10, ge=1, le=100)
    postgres_max_overflow: int = Field(default=5, ge=0, le=50)
    postgres_pool_pre_ping: bool = True
    postgres_echo: bool = False

    # ── Postgres column encryption ───────────────────────────────────
    db_master_key: SecretStr  # REQUIRED; openssl rand -base64 32

    # ── Redis ────────────────────────────────────────────────────────
    redis_host: str = "127.0.0.1"
    redis_port: int = Field(default=6379, ge=1, le=65535)
    redis_db_celery: int = 0
    redis_db_cache: int = 1
    redis_db_ratelimit: int = 2
    redis_password: SecretStr | None = None

    # ── S3 / MinIO ───────────────────────────────────────────────────
    # NOTE: S3_ACCESS_KEY treated as a plain string — for MinIO local-dev the
    # default value `minioadmin` is documented; treating it as a secret is
    # theatre. S3_SECRET_KEY is SecretStr for log-redaction.
    s3_endpoint_url: AnyHttpUrl = Field(default=AnyHttpUrl("http://127.0.0.1:9000"))
    s3_region: str = "us-east-1"
    s3_access_key: str = "minioadmin"
    s3_secret_key: SecretStr = SecretStr("minioadmin")
    s3_bucket: str = "nativ2-v0-1-local"
    s3_force_path_style: bool = True

    # ── Celery ───────────────────────────────────────────────────────
    # v0.1 = 2 queues (default + llm_heavy). v2 adds vendor_apis + rendering
    # per V2-SCALE-01.
    celery_broker_url: str = "redis://127.0.0.1:6379/0"
    celery_result_backend: str = "redis://127.0.0.1:6379/0"
    celery_task_track_started: bool = True
    celery_task_time_limit_seconds: int = 1800
    celery_worker_concurrency_default: int = Field(default=4, ge=1, le=64)
    celery_worker_concurrency_llm_heavy: int = Field(default=2, ge=1, le=16)

    # ── Anthropic ────────────────────────────────────────────────────
    anthropic_api_key: SecretStr  # REQUIRED
    anthropic_default_model: str = "claude-opus-4-7"
    anthropic_max_tokens_per_call: int = Field(default=8000, ge=1, le=64000)
    anthropic_prompt_caching_enabled: bool = True
    anthropic_request_timeout_seconds: int = Field(default=120, ge=1, le=600)
    anthropic_max_retries: int = Field(default=3, ge=0, le=10)

    # ── LLM cost budgets ─────────────────────────────────────────────
    llm_budget_daily_usd: float = Field(default=100.0, ge=0)
    llm_budget_per_pack_usd: float = Field(default=10.0, ge=0)
    llm_budget_hard_kill_daily_usd: float = Field(default=500.0, ge=0)

    # ── Vendor secrets (all optional at M0; per-phase milestones enforce) ──
    smartlead_api_key: SecretStr | None = None
    smartlead_webhook_secret: SecretStr | None = None
    smartlead_base_url: AnyHttpUrl = Field(default=AnyHttpUrl("https://server.smartlead.ai/api/v1"))

    exa_api_key: SecretStr | None = None
    exa_base_url: AnyHttpUrl = Field(default=AnyHttpUrl("https://api.exa.ai"))

    apollo_api_key: SecretStr | None = None
    linkedin_api_key: SecretStr | None = None

    meta_app_id: str | None = None
    meta_app_secret: SecretStr | None = None
    meta_webhook_verify_token: SecretStr | None = None

    tiktok_client_key: str | None = None
    tiktok_client_secret: SecretStr | None = None

    # ── Sentry ───────────────────────────────────────────────────────
    sentry_dsn: AnyHttpUrl | None = None
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    sentry_profiles_sample_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    # ── Langfuse ─────────────────────────────────────────────────────
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: AnyHttpUrl = Field(default=AnyHttpUrl("http://127.0.0.1:3000"))
    langfuse_enabled: bool = True

    # ── Transactional email ──────────────────────────────────────────
    transactional_email_provider: Literal["postmark", "resend", "none"] = "none"
    transactional_email_api_key: SecretStr | None = None
    transactional_email_from: str = "system@nativ2.local"

    # ── Idempotency ──────────────────────────────────────────────────
    idempotency_default_ttl_hours: int = Field(default=24, ge=1)
    idempotency_long_running_ttl_hours: int = Field(default=168, ge=1)

    # ── Tasks ────────────────────────────────────────────────────────
    task_retention_days: int = Field(default=30, ge=1)
    task_max_progress_poll_per_second: int = Field(default=5, ge=1, le=100)

    # ── Cron schedule overrides (seconds) ────────────────────────────
    cron_phase_4_5_auto_fire_seconds: int = 300
    cron_phase_4_8_detection_stories_seconds: int = 900
    cron_phase_4_8_detection_other_seconds: int = 3600
    cron_phase_4_9_kpi_capture_seconds: int = 86400
    cron_invoice_overdue_reminders_seconds: int = 86400
    cron_talent_stats_refresh_seconds: int = 604800
    cron_brand_handle_refresh_seconds: int = 604800
    cron_discovery_run_seconds: int = 2592000
    cron_enrollment_state_sync_seconds: int = 300
    cron_auto_archive_trigger_check_seconds: int = 900

    # ── Uploads ──────────────────────────────────────────────────────
    upload_max_file_size_mb: int = Field(default=100, ge=1, le=1024)
    upload_presign_ttl_seconds: int = Field(default=900, ge=1)

    # ── Memo store ───────────────────────────────────────────────────
    memo_inline_max_kb: int = Field(default=32, ge=1)

    # ── Performance / capacity ───────────────────────────────────────
    max_concurrent_pack_generations_per_agency: int = Field(default=5, ge=1)
    pack_generation_timeout_seconds: int = Field(default=1800, ge=1)

    # ── Safety toggles ───────────────────────────────────────────────
    require_idempotency_key_on_writes: bool = True
    enforce_template_version_bump: bool = True

    # ── Validators ───────────────────────────────────────────────────
    @model_validator(mode="after")
    def _validate_external_bind(self) -> Settings:
        if self.nativ2_bind_host != "127.0.0.1" and not self.nativ2_external_bind_confirmed:
            raise ValueError(
                f"NATIV2_BIND_HOST={self.nativ2_bind_host} requires explicit "
                "NATIV2_EXTERNAL_BIND_CONFIRMED=true. v0.1 is designed for "
                "127.0.0.1 only; see docs/auth_and_authorization.md."
            )
        return self

    @model_validator(mode="after")
    def _validate_llm_budgets(self) -> Settings:
        if self.llm_budget_hard_kill_daily_usd <= self.llm_budget_daily_usd:
            raise ValueError(
                f"LLM_BUDGET_HARD_KILL_DAILY_USD ({self.llm_budget_hard_kill_daily_usd}) "
                f"must exceed LLM_BUDGET_DAILY_USD ({self.llm_budget_daily_usd}). "
                "Soft alert threshold must be strictly less than the hard kill."
            )
        return self

    # ── Derived URLs ─────────────────────────────────────────────────
    @property
    def database_url_async(self) -> str:
        """Async DSN for SQLAlchemy + asyncpg."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:"
            f"{quote_plus(self.postgres_password.get_secret_value())}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Sync DSN for Alembic offline migrations + non-async tooling."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:"
            f"{quote_plus(self.postgres_password.get_secret_value())}@"
            f"{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton. Pydantic loads + validates exactly once."""
    return Settings()  # type: ignore[call-arg]


# Module-level singleton for convenient import.
settings: Settings = get_settings()
