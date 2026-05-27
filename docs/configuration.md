# Configuration

**Status:** Locked v0.1 (2026-05-26). All app config flows through `pydantic-settings`. No `os.environ` reads in domain code. See `docs/code_conventions.md` § 11.

The `.env.example` file at repo root ships with every variable enumerated + safe-to-commit defaults. Operators copy to `.env` + fill in secrets.

---

## 1. Settings model (target shape)

`app/config.py`:

```python
from typing import Literal
from pydantic import SecretStr, Field, AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",
    )

    # ─── App identity ────────────────────────────────────────────────────
    nativ2_environment: Literal["development", "test", "production"] = "development"
    nativ2_version: str = "0.1.0"

    # ─── FastAPI ────────────────────────────────────────────────────────
    nativ2_bind_host: str = "127.0.0.1"
    nativ2_bind_port: int = 8000
    nativ2_external_bind_confirmed: bool = False  # safety opt-in for 0.0.0.0
    nativ2_api_workers: int = 1

    # ─── Postgres ───────────────────────────────────────────────────────
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "nativ2"
    postgres_user: str = "nativ2"
    postgres_password: SecretStr
    postgres_pool_size: int = 10
    postgres_max_overflow: int = 5
    postgres_pool_pre_ping: bool = True
    postgres_echo: bool = False  # log SQL — only on in dev

    # ─── Postgres encryption ─────────────────────────────────────────────
    db_master_key: SecretStr  # pgcrypto master key for AES-256

    # ─── Redis ──────────────────────────────────────────────────────────
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db_celery: int = 0
    redis_db_cache: int = 1
    redis_db_ratelimit: int = 2
    redis_password: SecretStr | None = None

    # ─── S3 / MinIO (object storage) ────────────────────────────────────
    s3_endpoint_url: AnyHttpUrl = "http://127.0.0.1:9000"  # MinIO in v0.1
    s3_region: str = "us-east-1"
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_bucket: str = "nativ2-v0-1-local"
    s3_force_path_style: bool = True  # required for MinIO

    # ─── Celery ─────────────────────────────────────────────────────────
    # v0.1 = 2 queues (default + llm_heavy). v2 splits to 4 — V2-SCALE-01.
    celery_broker_url: str = "redis://127.0.0.1:6379/0"
    celery_result_backend: str = "redis://127.0.0.1:6379/0"
    celery_task_track_started: bool = True
    celery_task_time_limit_seconds: int = 1800  # 30 min default
    celery_worker_concurrency_default: int = 4
    celery_worker_concurrency_llm_heavy: int = 2

    # ─── Anthropic (Claude) ──────────────────────────────────────────────
    anthropic_api_key: SecretStr
    anthropic_default_model: str = "claude-opus-4-7"  # v0.1 = Opus 4.7 everywhere
    anthropic_max_tokens_per_call: int = 8000
    anthropic_prompt_caching_enabled: bool = True
    anthropic_request_timeout_seconds: int = 120
    anthropic_max_retries: int = 3

    # ─── LLM cost budgets ────────────────────────────────────────────────
    llm_budget_daily_usd: float = 100.0  # soft alert threshold
    llm_budget_per_pack_usd: float = 10.0  # per-pack soft cap
    llm_budget_hard_kill_daily_usd: float = 500.0  # hard kill if exceeded

    # ─── Smartlead ───────────────────────────────────────────────────────
    smartlead_api_key: SecretStr
    smartlead_webhook_secret: SecretStr
    smartlead_base_url: AnyHttpUrl = "https://server.smartlead.ai/api/v1"

    # ─── Exa (web research) ──────────────────────────────────────────────
    exa_api_key: SecretStr
    exa_base_url: AnyHttpUrl = "https://api.exa.ai"

    # ─── Apollo ──────────────────────────────────────────────────────────
    apollo_api_key: SecretStr | None = None  # optional — Phase 3a

    # ─── LinkedIn ────────────────────────────────────────────────────────
    linkedin_api_key: SecretStr | None = None  # optional — Phase 3a enrichment

    # ─── Meta Graph API ──────────────────────────────────────────────────
    meta_app_id: str | None = None  # optional — Phase 4.8 + 4.9
    meta_app_secret: SecretStr | None = None
    meta_webhook_verify_token: SecretStr | None = None

    # ─── TikTok Display API ──────────────────────────────────────────────
    tiktok_client_key: str | None = None
    tiktok_client_secret: SecretStr | None = None

    # ─── Observability — Sentry ──────────────────────────────────────────
    sentry_dsn: AnyHttpUrl | None = None
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 0.1
    sentry_profiles_sample_rate: float = 0.0

    # ─── Observability — Langfuse ────────────────────────────────────────
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: AnyHttpUrl = "http://127.0.0.1:3000"  # self-hosted in v0.1
    langfuse_enabled: bool = True

    # ─── Email transactional (system → agent notifications) ──────────────
    transactional_email_provider: Literal["postmark", "resend", "none"] = "none"
    transactional_email_api_key: SecretStr | None = None
    transactional_email_from: str = "system@nativ2.local"

    # ─── Idempotency ─────────────────────────────────────────────────────
    idempotency_default_ttl_hours: int = 24
    idempotency_long_running_ttl_hours: int = 168  # 7d for pack-gen kickoffs

    # ─── Tasks (long-running ops) ────────────────────────────────────────
    task_retention_days: int = 30
    task_max_progress_poll_per_second: int = 5  # rate-limit task polls

    # ─── Cron schedule overrides (seconds) ───────────────────────────────
    cron_phase_4_5_auto_fire_seconds: int = 300        # 5 min
    cron_phase_4_8_detection_stories_seconds: int = 900   # 15 min
    cron_phase_4_8_detection_other_seconds: int = 3600    # 1 hr
    cron_phase_4_9_kpi_capture_seconds: int = 86400       # daily
    cron_invoice_overdue_reminders_seconds: int = 86400
    cron_talent_stats_refresh_seconds: int = 604800       # weekly
    cron_brand_handle_refresh_seconds: int = 604800
    cron_discovery_run_seconds: int = 2592000              # monthly per talent
    cron_enrollment_state_sync_seconds: int = 300
    cron_auto_archive_trigger_check_seconds: int = 900

    # ─── File upload limits ─────────────────────────────────────────────
    upload_max_file_size_mb: int = 100  # presigned URL limits
    upload_allowed_mime_types: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "image/png", "image/jpeg",
        "text/markdown", "text/plain",
    ]
    upload_presign_ttl_seconds: int = 900  # 15 min

    # ─── Memo store ─────────────────────────────────────────────────────
    memo_inline_max_kb: int = 32  # >32kB offloads to S3 (v0.2)

    # ─── Performance + capacity ─────────────────────────────────────────
    max_concurrent_pack_generations_per_agency: int = 5
    pack_generation_timeout_seconds: int = 1800  # 30 min hard timeout

    # ─── Misc safety ────────────────────────────────────────────────────
    require_idempotency_key_on_writes: bool = True
    enforce_template_version_bump: bool = True  # GAP-07 + GAP-08 fix enforcement


settings = Settings()
```

---

## 2. .env.example (committed; copy to .env)

```bash
# ────────────────────────────────────────────────────────────────────
# NATIV2 v0.1 — local development .env.example
# Copy to .env and fill in secrets.
# ────────────────────────────────────────────────────────────────────

# App identity
NATIV2_ENVIRONMENT=development                          # development | test | production
NATIV2_VERSION=0.1.0

# FastAPI (defaults safe — 127.0.0.1 only)
NATIV2_BIND_HOST=127.0.0.1
NATIV2_BIND_PORT=8000
NATIV2_EXTERNAL_BIND_CONFIRMED=false                    # explicit opt-in to bind != 127.0.0.1
NATIV2_API_WORKERS=1

# Postgres (matches docker-compose.yml defaults)
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=nativ2
POSTGRES_USER=nativ2
POSTGRES_PASSWORD=changeme-local-only                   # REQUIRED — set even for local dev
POSTGRES_POOL_SIZE=10
POSTGRES_MAX_OVERFLOW=5
POSTGRES_POOL_PRE_PING=true
POSTGRES_ECHO=false                                     # true to log SQL (dev only)

# Postgres encryption (pgcrypto AES-256)
DB_MASTER_KEY=                                          # REQUIRED — generate via `openssl rand -base64 32`

# Redis (matches docker-compose.yml defaults)
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB_CELERY=0
REDIS_DB_CACHE=1
REDIS_DB_RATELIMIT=2
REDIS_PASSWORD=                                         # empty for local-only

# S3 / MinIO (matches docker-compose.yml defaults)
S3_ENDPOINT_URL=http://127.0.0.1:9000
S3_REGION=us-east-1
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=nativ2-v0-1-local
S3_FORCE_PATH_STYLE=true

# Celery (uses redis above)
CELERY_BROKER_URL=redis://127.0.0.1:6379/0
CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/0
CELERY_TASK_TRACK_STARTED=true
CELERY_TASK_TIME_LIMIT_SECONDS=1800
CELERY_WORKER_CONCURRENCY_DEFAULT=4
CELERY_WORKER_CONCURRENCY_LLM_HEAVY=2
CELERY_WORKER_CONCURRENCY_VENDOR_APIS=8
CELERY_WORKER_CONCURRENCY_RENDERING=2

# Anthropic (Claude) — REQUIRED
ANTHROPIC_API_KEY=                                      # REQUIRED — sk-ant-...
ANTHROPIC_DEFAULT_MODEL=claude-opus-4-7
ANTHROPIC_MAX_TOKENS_PER_CALL=8000
ANTHROPIC_PROMPT_CACHING_ENABLED=true
ANTHROPIC_REQUEST_TIMEOUT_SECONDS=120
ANTHROPIC_MAX_RETRIES=3

# LLM cost budgets
LLM_BUDGET_DAILY_USD=100.0
LLM_BUDGET_PER_PACK_USD=10.0
LLM_BUDGET_HARD_KILL_DAILY_USD=500.0

# Smartlead — required for Phase 3b
SMARTLEAD_API_KEY=
SMARTLEAD_WEBHOOK_SECRET=
SMARTLEAD_BASE_URL=https://server.smartlead.ai/api/v1

# Exa — required for Phase 2 + 4.5/4.6/4.9 research
EXA_API_KEY=
EXA_BASE_URL=https://api.exa.ai

# Apollo — optional, Phase 3a
APOLLO_API_KEY=

# LinkedIn — optional, Phase 3a enrichment
LINKEDIN_API_KEY=

# Meta Graph — optional, Phase 4.8 detection + Phase 4.9 KPI capture
META_APP_ID=
META_APP_SECRET=
META_WEBHOOK_VERIFY_TOKEN=

# TikTok — optional, Phase 4.8 + 4.9
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=

# Sentry — optional in dev; recommended in production
SENTRY_DSN=
SENTRY_ENVIRONMENT=development
SENTRY_TRACES_SAMPLE_RATE=0.1
SENTRY_PROFILES_SAMPLE_RATE=0.0

# Langfuse (self-hosted by default; matches docker-compose.yml)
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=http://127.0.0.1:3000
LANGFUSE_ENABLED=true

# Transactional email — optional
TRANSACTIONAL_EMAIL_PROVIDER=none                       # postmark | resend | none
TRANSACTIONAL_EMAIL_API_KEY=
TRANSACTIONAL_EMAIL_FROM=system@nativ2.local

# Idempotency
IDEMPOTENCY_DEFAULT_TTL_HOURS=24
IDEMPOTENCY_LONG_RUNNING_TTL_HOURS=168

# Tasks
TASK_RETENTION_DAYS=30
TASK_MAX_PROGRESS_POLL_PER_SECOND=5

# Cron schedule overrides (seconds)
CRON_PHASE_4_5_AUTO_FIRE_SECONDS=300
CRON_PHASE_4_8_DETECTION_STORIES_SECONDS=900
CRON_PHASE_4_8_DETECTION_OTHER_SECONDS=3600
CRON_PHASE_4_9_KPI_CAPTURE_SECONDS=86400
CRON_INVOICE_OVERDUE_REMINDERS_SECONDS=86400
CRON_TALENT_STATS_REFRESH_SECONDS=604800
CRON_BRAND_HANDLE_REFRESH_SECONDS=604800
CRON_DISCOVERY_RUN_SECONDS=2592000
CRON_ENROLLMENT_STATE_SYNC_SECONDS=300
CRON_AUTO_ARCHIVE_TRIGGER_CHECK_SECONDS=900

# File uploads
UPLOAD_MAX_FILE_SIZE_MB=100
UPLOAD_PRESIGN_TTL_SECONDS=900

# Memo store
MEMO_INLINE_MAX_KB=32

# Performance
MAX_CONCURRENT_PACK_GENERATIONS_PER_AGENCY=5
PACK_GENERATION_TIMEOUT_SECONDS=1800

# Safety toggles
REQUIRE_IDEMPOTENCY_KEY_ON_WRITES=true
ENFORCE_TEMPLATE_VERSION_BUMP=true
```

---

## 3. Per-environment differences

| Setting | development | test | production |
|---|---|---|---|
| `NATIV2_ENVIRONMENT` | `development` | `test` | `production` |
| `POSTGRES_ECHO` | configurable | false (perf) | false |
| `SENTRY_TRACES_SAMPLE_RATE` | 0.0 or 0.1 | 0.0 | 0.1-0.5 |
| `SENTRY_DSN` | optional | unset | required |
| `LANGFUSE_ENABLED` | true (local) | false | true (cloud) |
| `LLM_BUDGET_DAILY_USD` | 50 | 0 (use cassettes) | per-customer |
| `MAX_CONCURRENT_PACK_GENERATIONS_PER_AGENCY` | 5 | 1 (serialise tests) | 10 |
| `ANTHROPIC_API_KEY` | required | required (for `live_llm` nightly only) | required |
| `NATIV2_API_WORKERS` | 1 | 1 | 4+ |

CI loads env via `.env.test` (or uses pytest envvar fixtures); production loads via container env vars.

---

## 4. Validation at app start

`app/main.py` lifespan event validates settings at startup:

```python
from contextlib import asynccontextmanager
from app.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Defensive: refuse to start with 0.0.0.0 bind unless explicitly confirmed
    if settings.nativ2_bind_host == "0.0.0.0" and not settings.nativ2_external_bind_confirmed:
        raise RuntimeError(
            "Refusing to bind to 0.0.0.0 without NATIV2_EXTERNAL_BIND_CONFIRMED=true. "
            "v0.1 is designed for 127.0.0.1 local-only. See docs/auth_and_authorization.md."
        )

    # Validate required secrets at startup (fail fast)
    required_secrets = [
        ("DB_MASTER_KEY", settings.db_master_key),
        ("ANTHROPIC_API_KEY", settings.anthropic_api_key),
        ("POSTGRES_PASSWORD", settings.postgres_password),
    ]
    for name, value in required_secrets:
        if not value or not value.get_secret_value():
            raise RuntimeError(f"{name} is required but not set in .env")

    yield
```

---

## 5. Secrets that must NEVER be committed

These appear in `.env.example` as empty fields. Strict policy: never check in values for these:

- `POSTGRES_PASSWORD`
- `DB_MASTER_KEY`
- `REDIS_PASSWORD`
- `S3_SECRET_KEY` (MinIO defaults are pseudo-secrets and OK to commit; production replacements are not)
- `ANTHROPIC_API_KEY`
- `SMARTLEAD_API_KEY` + `SMARTLEAD_WEBHOOK_SECRET`
- `EXA_API_KEY`
- `APOLLO_API_KEY`
- `LINKEDIN_API_KEY`
- `META_APP_SECRET` + `META_WEBHOOK_VERIFY_TOKEN`
- `TIKTOK_CLIENT_SECRET`
- `SENTRY_DSN`
- `LANGFUSE_SECRET_KEY`
- `TRANSACTIONAL_EMAIL_API_KEY`

Pre-commit hook scans for these patterns via trufflehog + a custom check matching the env var names above. Block commits that contain plausible secret values for these keys.

---

## 6. Pydantic SecretStr handling

Secrets use `SecretStr` to prevent accidental logging:

```python
api_key = settings.anthropic_api_key.get_secret_value()  # explicit unwrap

# Logging the entire settings object is safe — SecretStr renders as "***":
log.info("settings_loaded", settings=settings.model_dump())
# Output: { "anthropic_api_key": "**********", ... }
```

---

## 7. Adding a new env var

When you need a new config value:

1. Add the field to `app/config.py` Settings class with a default (if non-secret) or `SecretStr` (if secret).
2. Add the entry to `.env.example` with a clear comment about what it controls.
3. Update this doc (`docs/configuration.md`) § 1 + § 2.
4. If per-environment differences apply, update § 3.
5. If it's a secret, update § 5.
6. Add a test in `tests/unit/test_config.py` that exercises a non-default value.
