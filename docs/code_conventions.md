# Code Conventions

**Status:** Locked v0.1 (2026-05-26). Every Python file in `app/` MUST follow these conventions. Enforced via aggressive pre-commit hooks (ruff lint + ruff format + pyright strict + schema codegen drift check + unit tests for changed files + trufflehog secret scan + JSON Schema validation).

---

## 1. Python style

### 1.1 Toolchain

| Tool | Purpose | Config |
|---|---|---|
| **Python 3.12** (exact) | Runtime | `.python-version` (uv / pyenv) |
| **uv** | Dependency + venv management | `pyproject.toml` + `uv.lock` (committed) |
| **ruff** | Lint + format (replaces black + isort + flake8) | `pyproject.toml` `[tool.ruff]` |
| **pyright** strict | Type-check | `pyproject.toml` `[tool.pyright]` |
| **pytest** | Test runner | `pyproject.toml` `[tool.pytest.ini_options]` |
| **alembic** | DB migrations | `alembic.ini` + `alembic/` |

### 1.2 ruff config (target)

```toml
[tool.ruff]
line-length = 100
target-version = "py312"
extend-exclude = ["alembic/versions/", "app/models/pydantic/"]  # generated code

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "ANN", "ASYNC", "S", "C4", "DTZ", "PIE", "PT", "RET", "SIM", "TID", "ARG", "PL", "RUF"]
ignore = ["ANN101", "ANN102"]  # self/cls annotations not required
unfixable = ["B"]

[tool.ruff.lint.isort]
known-first-party = ["app", "tests"]
```

Key rules:
- **Line length:** 100 (not 88; not 120).
- **Imports:** isort-style; `app.*` first-party, separated from third-party.
- **Datetime safety (DTZ):** `datetime.now()` is forbidden — always use `datetime.now(UTC)` or `datetime.now(timezone.utc)`. Pre-commit blocks naive datetimes.
- **Async safety (ASYNC):** flags blocking calls inside async functions.
- **Security (S):** flags pickle, eval, exec, MD5, hardcoded passwords.

### 1.3 pyright config

```toml
[tool.pyright]
include = ["app", "tests"]
exclude = ["app/models/pydantic/**", "alembic/versions/**"]
strict = ["app/**"]
typeCheckingMode = "strict"
reportMissingTypeStubs = false
```

Strict mode requires:
- Every function annotated (params + return).
- No implicit `Any`.
- No untyped function calls.

---

## 2. Naming conventions

| Kind | Convention | Example |
|---|---|---|
| Modules | `snake_case.py` | `app/services/posting_detection.py` |
| Packages | `snake_case/` | `app/agents/skills/` |
| Classes | `PascalCase` | `DealOrchestratorAgent`, `BrandCandidateRepository` |
| Functions / methods | `snake_case` | `compose_context_bundle`, `read_memos` |
| Variables | `snake_case` | `talent_id`, `agency_profile` |
| Constants | `SCREAMING_SNAKE_CASE` | `MAX_RETRY_ATTEMPTS`, `DEFAULT_CACHE_TTL_SECONDS` |
| Private | `_leading_underscore` (single only — double-underscore avoided) | `_compute_match_score` |
| Type aliases | `PascalCase` | `JsonDict = dict[str, Any]` |
| Pydantic models | `PascalCase` with no `Model` suffix | `Talent`, `BrandCandidate`, `MemoCreate`, `MemoOut` |
| SQLAlchemy models | `PascalCase` mirroring Pydantic (suffix `Row` only if collision) | `Talent` (table `talent`), `Memo` (table `memo`) |
| Enum members | `SCREAMING_SNAKE_CASE` | `DealStage.LEAD`, `DealStage.PROPOSAL` |
| Test functions | `test_<unit>__<scenario>__<expected>` | `test_prep_pack_gen__brand_handle_missing__omits_handle_signal` |

### 2.1 Schema-Pydantic-SQLAlchemy alignment

For schema `talent.schema.json`:
- Pydantic: `app/models/pydantic/talent.py` → `class Talent(BaseModel)`
- SQLAlchemy: `app/models/sqla/talent.py` → `class Talent(Base)` mapped to table `talent`

The Pydantic + SQLAlchemy classes share the name (importing requires alias when both needed in one file).

---

## 3. Async discipline

### 3.1 When to use async

- **All FastAPI route handlers:** `async def`.
- **All repository methods:** `async def` (async SQLAlchemy session).
- **All vendor wrappers:** `async def` (httpx.AsyncClient).
- **All Celery tasks:** `def` (sync) — Celery doesn't natively support async. Tasks that need async vendor calls wrap with `asyncio.run(...)`.
- **All agent code:** `async def` (Claude Agent SDK is async).

### 3.2 No mixing in service layer

A function is either fully async or fully sync. Don't do:

```python
# WRONG
async def get_talent(talent_id: str) -> Talent:
    return talent_repo.get_sync(talent_id)  # blocking call in async function
```

### 3.3 Async context managers

DB transactions, S3 sessions, httpx clients use async context managers:

```python
async with async_session() as session:
    async with session.begin():
        result = await session.execute(stmt)
        ...
```

---

## 4. Custom exception hierarchy

All exceptions raised inside `app/` derive from a single root. Maps cleanly to HTTP status codes via a FastAPI exception handler.

```python
# app/errors.py

class NATIV2Error(Exception):
    """Root for all app-internal exceptions."""
    code: str = "INTERNAL_UNEXPECTED"
    http_status: int = 500
    user_message: str = "Something went wrong."

class ValidationError(NATIV2Error):
    """422. Input failed validation."""
    code = "VALIDATION_ERROR"
    http_status = 422

class BusinessRuleError(NATIV2Error):
    """422. Input is structurally valid but breaks a business rule (e.g. invalid state transition)."""
    code = "BUSINESS_RULE_VIOLATED"
    http_status = 422

class NotFoundError(NATIV2Error):
    """404. Resource doesn't exist for this agency."""
    code = "NOT_FOUND"
    http_status = 404

class ConflictError(NATIV2Error):
    """409. Optimistic-lock or idempotency conflict."""
    code = "CONFLICT"
    http_status = 409

class OptimisticLockError(ConflictError):
    code = "CONFLICT_OPTIMISTIC_LOCK"

class IdempotencyMismatchError(ConflictError):
    code = "CONFLICT_IDEMPOTENCY_MISMATCH"

class IntegrationError(NATIV2Error):
    """502. Upstream vendor failure."""
    code = "INTEGRATION_ERROR"
    http_status = 502
    vendor: str = ""

class IntegrationTimeoutError(IntegrationError):
    code = "INTEGRATION_TIMEOUT"

class IntegrationRateLimitError(IntegrationError):
    code = "INTEGRATION_RATE_LIMITED"
    http_status = 429

class DegradedModeError(NATIV2Error):
    """503. Feature degraded (LLM budget exceeded; vendor disabled)."""
    code = "DEGRADED_MODE"
    http_status = 503

class AuthorizationError(NATIV2Error):
    """403 (v2). Authenticated user lacks permission."""
    code = "FORBIDDEN"
    http_status = 403
```

### 4.1 Raising

Always include enough context for the response envelope's `errors[]` entry:

```python
raise BusinessRuleError(
    code="BUSINESS_RULE_VIOLATED",
    message=f"Cannot advance deal {deal_id} from {current.substage} to {new.substage}: illegal transition",
    field="substage",
    detail={"current": current.substage, "attempted": new.substage, "allowed": ALLOWED_TRANSITIONS[current.substage]},
)
```

### 4.2 Handling

The FastAPI exception handler converts `NATIV2Error` instances to envelope responses:

```python
@app.exception_handler(NATIV2Error)
async def nativ2_error_handler(request: Request, exc: NATIV2Error) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "data": None,
            "meta": {"request_id": request_id_var.get(), "timestamp": now_iso(), "api_version": "v1"},
            "errors": [{
                "code": exc.code,
                "message": exc.user_message or str(exc),
                "field": getattr(exc, "field", None),
                "detail": getattr(exc, "detail", None),
            }],
        },
    )
```

Unexpected exceptions (not `NATIV2Error`) → 500 + Sentry capture + generic message (no internal detail leaked).

---

## 5. Logging conventions

### 5.1 structlog setup

```python
# app/utils/logging.py

import structlog

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()
```

### 5.2 Required context keys

Every log line should carry these context keys when applicable (set via `structlog.contextvars.bind_contextvars` in middleware + Celery task setup):

| Key | When | Source |
|---|---|---|
| `request_id` | Always (in API context) | FastAPI middleware reads from `X-Request-Id` header or generates |
| `agency_id` | Always | `current_agency_id()` |
| `agent_id` | Always (in agent-action context) | `current_agent_id()` |
| `talent_id` | When operating on a talent | Route param |
| `deal_id` | When operating on a deal | Route param |
| `pack_id` | When operating on a pack | Route param |
| `pack_type` | Pack generation | Pack-orchestrator |
| `task_id` | Long-running operation | Task service |
| `vendor` | Vendor wrapper calls | Vendor module |
| `correlation_id` | Cross-system tracing (e.g. webhook → cron → API) | Propagated from upstream |

### 5.3 Levels

| Level | When |
|---|---|
| `DEBUG` | Verbose dev info; off in prod |
| `INFO` | Normal operations (request received, task started, vendor call succeeded) |
| `WARNING` | Recoverable issues (vendor retry, cache miss, degraded mode) |
| `ERROR` | Failed operations + handled exceptions |
| `CRITICAL` | System integrity issues (multi-agency at startup; key missing; pgcrypto error) |

### 5.4 Example

```python
log.info(
    "prep_pack_generation_started",
    deal_id=deal_id,
    pack_type="discovery_prep_pack",
    pack_id=pack_id,
    triggering_event="substage_transition_initial_call_scheduled",
)

try:
    pack = await orchestrator.generate_prep_pack(deal_id=deal_id)
    log.info(
        "prep_pack_generation_completed",
        deal_id=deal_id,
        pack_id=pack.prep_pack_id,
        duration_seconds=elapsed,
        llm_cost_usd=pack.generation.total_cost_usd,
    )
except IntegrationError as exc:
    log.error(
        "prep_pack_generation_failed",
        deal_id=deal_id,
        pack_id=pack_id,
        vendor=exc.vendor,
        exc_info=True,
    )
    raise
```

### 5.5 Event names

Snake_case past-tense for completed events (`prep_pack_generation_completed`) or present-tense for in-flight (`prep_pack_generation_started`). Avoid generic events ("error" / "info"); pick a specific event name. Build a `docs/log_event_catalog.md` (proposed — not yet shipped) as events accrete in v0.2.

### 5.6 No PII in logs

Strict policy: NEVER log:
- Email addresses (use `email_domain` if needed)
- Talent legal names (use `talent_id` slug)
- Brand legal entity legal names (use `brand_id` slug)
- Contract clause text
- Memo content
- Raw API tokens

Pre-commit hook checks for likely PII patterns in log strings via trufflehog + a custom check.

---

## 6. Soft-delete pattern (system-wide)

Per locked decision: every domain table carries soft-delete columns.

### 6.1 Columns

```python
# Mixin applied to all domain SQLAlchemy models

class SoftDeleteMixin:
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_agent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

**v0.1 simplification (V2-DATA-07):** `deleted_by_agent_id` defaults to the singleton agent (`current_agent_id()`) in v0.1 — there is only one operator, so the column is auto-populated by the API layer without requiring explicit input. v2 will enforce population from the JWT-derived agent_id and reject writes without it. The column stays in the schema for v2-readiness.

### 6.2 Repository discipline

ALL repository read methods filter by `is_deleted == False` by default:

```python
async def get_by_id(self, talent_id: str) -> Talent | None:
    stmt = select(Talent).where(
        Talent.id == talent_id,
        Talent.agency_id == self.current_agency_id,
        Talent.is_deleted == False,
    )
    return (await self.session.execute(stmt)).scalar_one_or_none()
```

To explicitly include soft-deleted rows, pass `include_deleted=True`:

```python
async def get_by_id(self, talent_id: str, *, include_deleted: bool = False) -> Talent | None: ...
```

Use cases for `include_deleted=True`:
- Admin views (restore deleted record)
- Cross-deal memo retrieval (sometimes needed to show "this brand was previously deleted")
- v2 GDPR purge tooling (find then hard-delete)

### 6.3 Delete endpoint

```python
@router.delete("/api/v1/talents/{talent_id}")
async def soft_delete_talent(
    talent_id: str,
    agent_id: str = Depends(current_agent_id),
    repo: TalentRepository = Depends(),
) -> APIResponse[Talent]:
    talent = await repo.soft_delete(talent_id, deleted_by_agent_id=agent_id)
    return APIResponse(data=talent, meta=...)
```

The soft-deleted record is returned (so UI can show "Restored?" prompt + audit trail).

### 6.4 Hard delete

Hard-delete is reserved for:
- v2 GDPR right-to-erasure (separate tool, not exposed as API endpoint)
- Test cleanup (transaction rollback handles this in tests)

Never expose hard-delete through agent API surfaces.

### 6.5 Memo's `is_active` alignment

`memo.is_active` semantic == `NOT is_deleted`. Soft-delete columns added in M1; `is_active` becomes a computed property:

```python
@property
def is_active(self) -> bool:
    return not self.is_deleted and (self.expires_at is None or self.expires_at > datetime.now(UTC))
```

---

## 7. Money handling

### 7.1 Decimal everywhere

Per locked decision:

```python
from decimal import Decimal

# Pydantic
class Deal(BaseModel):
    fee_usd: Decimal = Field(..., ge=0, max_digits=12, decimal_places=2)

# SQLAlchemy
fee_usd: Mapped[Decimal] = mapped_column(Numeric(precision=12, scale=2))

# JSON serialisation
class Config:
    json_encoders = {Decimal: lambda v: f"{v:.2f}"}  # serialise as string for precision
```

### 7.2 Arithmetic rules

- Sums + subtractions are exact.
- Multiplications: result is Decimal × Decimal = Decimal (exact).
- Divisions: explicit rounding using `Decimal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)`.
- NEVER mix Decimal + float in arithmetic; raises by design.

### 7.3 Computed monetary fields

CPM / CPE / CTR etc:

```python
from decimal import Decimal, ROUND_HALF_UP

def compute_cpm(fee_usd: Decimal, impressions: int) -> Decimal:
    if impressions == 0:
        return Decimal("0.00")
    raw = (fee_usd / Decimal(impressions)) * Decimal(1000)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

### 7.4 Multi-currency

`fee_usd` is the USD-normalised analytics field. The original capture is `fee_currency_original` (ISO 4217 code) + `fee_original_amount` (Decimal). FX conversion to USD happens at proposal time with an FX timestamp:

```python
class CommercialProposal(BaseModel):
    fee_currency_original: str = Field(..., pattern=r"^[A-Z]{3}$", default="USD")
    fee_original_amount: Decimal = Field(...)
    fee_usd: Decimal = Field(...)
    fee_fx_rate: Decimal | None = Field(None)
    fee_fx_at: datetime | None = Field(None)
```

`fee_currency_original == "USD"` → `fee_usd == fee_original_amount` + no FX fields. Other currencies require FX rate + timestamp at the moment of commercial gate confirmation. Brand-facing rendering uses `fee_original_amount + fee_currency_original`. Analytics + invoice schedule math uses `fee_usd`.

---

## 8. Date + time

### 8.1 UTC everywhere

```python
from datetime import datetime, UTC

# Always tz-aware
now = datetime.now(UTC)

# Reject naive datetimes at boundaries
class Memo(BaseModel):
    created_at: datetime = Field(...)

    @field_validator("created_at")
    @classmethod
    def must_be_tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("must be timezone-aware (use UTC)")
        return v.astimezone(UTC)
```

### 8.2 ISO 8601 serialisation

All datetimes serialised with `Z` suffix:

```python
class Config:
    json_encoders = {
        datetime: lambda v: v.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z",
    }
```

### 8.3 SQLAlchemy timezone

```python
created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

`DateTime(timezone=True)` ensures Postgres stores as `TIMESTAMPTZ`.

### 8.4 Dates (not datetimes)

For pure dates (`as_of`, `birth_date`, `payment_date`), use `datetime.date` + Pydantic `date` type. No timezone confusion.

### 8.5 Forbidden patterns

ruff DTZ rules + a custom check block:
- `datetime.now()` without args (naive)
- `datetime.utcnow()` (returns naive)
- `time.time()` in domain code (use `datetime.now(UTC).timestamp()` if a unix epoch is genuinely needed)
- Naive datetime constructors

---

## 9. Comments + docstrings

### 9.1 Default: no comments

Code is self-documenting via well-named identifiers. Don't:

```python
# Get the talent
talent = repo.get(talent_id)
```

That comment is noise.

### 9.2 When to comment

Only when the WHY is non-obvious + not derivable from the code:
- Hidden constraints ("Smartlead caps at 5 emails/day per mailbox during warmup")
- Subtle invariants ("This sort must be stable to preserve user-specified order")
- Workarounds for specific bugs ("This works around Anthropic API returning 502 on tokenizer mismatch — remove after SDK 4.1")
- Behaviour that would surprise a reader

### 9.3 Docstrings

Used for PUBLIC interfaces (exported functions, classes, modules) where the reader is likely to be unfamiliar with the unit. One-line docstring summarising purpose:

```python
def compute_match_score(post: PostCandidate, expected: PostingScheduleEntry) -> int:
    """Compute 0-100 match score from per-signal points. See docs/invoice_workflow.md § Layer 1."""
    ...
```

Multi-paragraph docstrings only for genuinely complex behaviour. Reference the workflow doc instead of duplicating it.

### 9.4 Generated code

Auto-generated Pydantic models in `app/models/pydantic/` include the source schema $id as a docstring; no other commentary.

---

## 10. Testing conventions

### 10.1 Test file location

Mirrors the source tree:

```
app/services/posting_detection.py
tests/unit/services/test_posting_detection.py
tests/integration/services/test_posting_detection_integration.py
```

### 10.2 Test function naming

`test_<unit>__<scenario>__<expected>`:

```python
def test_compute_match_score__all_signals_match__returns_100() -> None: ...
def test_compute_match_score__brand_handle_missing__omits_handle_signal() -> None: ...
def test_compute_match_score__time_outside_window__returns_zero() -> None: ...
```

Double-underscore separator gives clear visual reading even in CI output.

### 10.3 Fixtures

Use factory_boy factories per schema (in `tests/factories/`). Tests construct domain objects via factories, never raw dicts:

```python
def test_deal_state_machine__advance_lead_to_proposal__updates_substage() -> None:
    deal = DealFactory(stage="LEAD", substage="awaiting_initial_call")
    advanced = state_machine.advance(deal, target_substage="initial_call_scheduled")
    assert advanced.substage == "initial_call_scheduled"
```

### 10.4 Async tests

`pytest-asyncio` auto mode:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

All `async def test_*` functions are auto-discovered.

### 10.5 Parameterisation

For state-machine tests + similar combinatorial cases:

```python
@pytest.mark.parametrize("from_substage, to_substage, should_succeed", [
    ("awaiting_initial_call", "initial_call_scheduled", True),
    ("awaiting_initial_call", "proposal_drafted", False),
    # ...
])
def test_state_transition(from_substage: str, to_substage: str, should_succeed: bool) -> None: ...
```

### 10.6 Marker conventions

```toml
[tool.pytest.ini_options]
markers = [
    "live: requires live external API keys (gated; skip by default)",
    "llm_eval: LLM eval test (cassette-based by default)",
    "llm_eval_record: re-record LLM cassette (writes to disk)",
    "live_llm: real Anthropic API call (nightly only)",
    "e2e: end-to-end test through FastAPI",
    "requires_real_fixture: needs ~/.nativ/test_fixtures/ present",
    "slow: takes > 5s",
]
```

---

## 11. Configuration access

All config via `app/config.py` + `pydantic-settings`. NEVER read `os.environ` directly in domain code.

```python
# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    anthropic_api_key: SecretStr
    db_master_key: SecretStr
    nativ2_bind_host: str = "127.0.0.1"
    nativ2_environment: Literal["development", "test", "production"] = "development"
    # ...

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
```

Domain code:

```python
from app.config import settings

async def call_anthropic() -> ...:
    api_key = settings.anthropic_api_key.get_secret_value()
    ...
```

See `docs/configuration.md` for the full env var inventory.

---

## 12. File organisation per module type

### 12.1 Service module

Single class or set of related functions. ~200-500 lines max; split if growing larger.

```
app/services/posting_detection.py
  - PostingDetectionService (class)
  - scoring algorithm constants
  - public methods: detect_candidate_matches, confirm_match, reject_match
  - private methods: _compute_match_score, _evaluate_*
```

### 12.2 Repository module

One repository per Postgres table. Single class with async methods.

```
app/repositories/deal.py
  - DealRepository
    - get_by_id
    - list_by_talent
    - list_by_stage
    - create
    - update_with_optimistic_lock
    - soft_delete
```

### 12.3 API module

One file per route group (matches OpenAPI tags from `docs/api_conventions.md` § 12).

```
app/api/deals.py
  - APIRouter("/api/v1/talents/{talent_id}/deals", tags=["Phase 4 — Deal Lifecycle"])
  - GET /, GET /{deal_id}, POST /, PATCH /{deal_id}, POST /{deal_id}:advance
```

### 12.4 Agent module

```
app/agents/
  base.py                # Agent base class
  coordinator.py         # DealOrchestratorAgent
  skills/
    researcher.py
    writer.py
    extractor.py
    renderer.py
  tools/                 # Shared tool catalog
    get_talent.py
    read_memos.py
    write_memo.py
    ...
  packs/
    discovery_prep.py    # Pack-specific coordinator subclasses
    proposal.py
    contract.py
    invoice.py
    performance_report.py
  bundles.py             # Context bundle composers
```

---

## 13. Don't-do list (anti-patterns)

| ❌ Avoid | ✅ Do instead |
|---|---|
| `from app import *` | Explicit imports |
| `Any` type hint (in app/) | Specific type or `object` |
| Bare `except:` | `except SpecificError:` or `except Exception:` with re-raise |
| `print()` in app code | `log.info(...)` |
| Naive `datetime.now()` | `datetime.now(UTC)` |
| `float` for money | `Decimal` |
| Hard-coded magic numbers | Module-level constants |
| Comments restating code | Self-documenting names |
| Multi-paragraph docstrings | Link to `docs/{workflow}.md` |
| Mutating function arguments | Return new value; pure functions |
| Module-level state | Dependency injection |
| Hard delete via API | Soft delete |
| `os.environ.get(...)` outside `app/config.py` | `settings.foo` |
| TODO without ticket reference | Either fix it or open an issue + link |
| Catch and swallow exceptions | Log + re-raise or convert to `NATIV2Error` |

---

## 14. Commit hygiene

See `CONTRIBUTING.md` for the full git workflow. Key rules:

- **Commit message:** descriptive subject (<72 chars) + body explaining WHY. Conventional Commits not enforced but encouraged.
- **One concern per commit:** schema change + handler change + test in one commit if they belong together. Don't mix unrelated refactors.
- **Tests must pass:** pre-commit blocks broken commits.
- **Branch naming:** `feature/{short-name}`, `fix/{short-name}`, `chore/{short-name}`.
