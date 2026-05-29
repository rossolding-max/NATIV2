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
    field_validator,
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

    # ── Discovery: last30days skill (M7 Search 16) ───────────────────
    # Off by default — the skill needs real OpenAI + xAI API keys and
    # produces only a modest signal weight (0.06). Flip on per-env once
    # the skill's auth + cost guards are configured for your installation.
    enable_last30days_discovery: bool = False

    # ── Discovery: comprehensiveness softener (M7.4) ────────────────
    # M7.4 dropped the orchestrator-level industry cap that pre-filtered
    # before any search ran. M7.6 re-introduces a SEPARATE cap that only
    # bounds the Exa-driven fan-out (S15/S18) — S5/6/7/8 still walk the
    # full industry list cheaply against the seed map. The cap keeps
    # Exa cost predictable when a talent's past-brand bidirectional walk
    # explodes the industry seed (Kevin: 12 past brands → 62 industries).
    #
    # Per-run cost at the default: 25 industries x 13 queries x 5 results
    # = ~1600 Exa calls (~$8) + ~325 Haiku calls (~$0.30). Bump higher
    # only if budget allows.
    discovery_exa_max_industries: int = Field(default=25, ge=1, le=200)
    #
    # The LLM softener (Haiku) augments the deterministic affinity walk
    # with industries the hand-curated affinity rows don't enumerate.
    # Off this to keep the discovery run deterministic in tests / cheap.
    discovery_industry_softener_enabled: bool = True

    # ── Discovery: M7.7 Phase 2 categories ──────────────────────────
    # The Phase 2 brand-universe build fires per-industry Exa queries
    # across emerging + established by default. M7.7 adds a "growth"
    # category (mid-market / Series C+ / regional leaders) to close
    # the gap between the two. Off cuts Phase 2 cost by ~33%.
    discovery_growth_enabled: bool = True

    # ── Discovery: paid social ad signal (M7.2 Search 17) ────────────
    # Off by default — Search 17 requires a Meta Ad Library token and hits
    # TikTok's unofficial public endpoint. Enable per-agency once the
    # token is provisioned + a manual smoke run on one talent looks clean.
    enable_search_17_paid_social: bool = False
    meta_ads_api_token: SecretStr | None = None
    meta_ads_default_countries: list[str] = Field(default_factory=lambda: ["US", "UK", "AU"])
    paid_social_min_active_ads: int = Field(default=5, ge=1)
    """Minimum active ads (last 30 days) for a brand to count as 'paid social active'."""
    paid_social_max_industries_per_run: int = Field(default=3, ge=1, le=10)
    """Cost cap — Search 17 fans out across this many of the talent's top industries."""

    apollo_api_key: SecretStr | None = None
    # RapidAPI gateway key. Used by LinkedInScraperClient (RapidAPI's
    # "Real-Time LinkedIn Scraper API" at linkedin-data-api.p.rapidapi.com).
    # Deprecated alias ``linkedin_api_key`` is kept until M5 to avoid breaking
    # .env files written before M3.
    rapidapi_key: SecretStr | None = None
    linkedin_api_key: SecretStr | None = None  # deprecated alias for rapidapi_key

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

    # ── Phase 4.5 discovery prep pack (M11) ──────────────────────────
    enable_phase_4_5_auto_fire: bool = False
    """Gate the M10 5-min cron's send_task: when False, the cron still walks
    find_ready_for_prep_pack() and stamps data.prep_pack_enqueued_at, but
    does NOT enqueue a pack-generation task. Manual POST /prep-pack/generate
    works regardless. Default False until 3-5 manual packs smoke-tested."""

    discovery_prep_model: str = "claude-opus-4-7"
    """LLM identifier used for all 4 passes of the discovery prep pack. v0.1
    default Opus 4.7; settings override allows downshift to claude-sonnet-4-6
    for cost optimisation."""

    # ── Safety toggles ───────────────────────────────────────────────
    require_idempotency_key_on_writes: bool = True
    enforce_template_version_bump: bool = True

    # ── Validators ───────────────────────────────────────────────────
    @field_validator("redis_password", mode="before")
    @classmethod
    def _empty_redis_password_is_none(cls, value: object) -> object:
        # An empty ``REDIS_PASSWORD=`` in .env parses to ``""`` and then
        # wraps as ``SecretStr("")`` — but every Redis consumer checks
        # ``if password is not None``, so the wrapper would force an
        # ``AUTH ""`` command and fail against a Redis with no password.
        # Treat the empty string as "no password configured" at parse time.
        #
        # Also defend against python-dotenv leaving a trailing inline
        # comment as the value when the .env line is shaped like
        # ``REDIS_PASSWORD=                  # comment``: dotenv keeps
        # the literal `# comment` because there's no value before it.
        # See docs/configuration.md for the canonical .env layout.
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped.startswith("#"):
                return None
        return value

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
    def _backfill_rapidapi_from_legacy(self) -> Settings:
        """Promote deprecated ``linkedin_api_key`` into ``rapidapi_key``.

        M3 renamed the field. Until the next release, callers can still set
        ``LINKEDIN_API_KEY`` in their .env; we read it here and surface it
        through the canonical field.
        """
        if self.rapidapi_key is None and self.linkedin_api_key is not None:
            self.rapidapi_key = self.linkedin_api_key
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
