# CLAUDE.md

This file gives Claude Code (and other AI assistants) durable context about this codebase. Read first when starting any work in this repo.

---

## What this is

**NATIV2** is an AI influencer marketing assistant for talent agencies. End-to-end pipeline:

1. **Phase 0** — Agency setup (one-time per agency)
2. **Phase 1** — Talent onboarding (per talent)
3. **Phase 1.5** — Past brand_deal capture
4. **Phase 2** — Brand discovery (16 searches surface candidate brands per talent)
5. **Phase 3a** — Contact CRM (enrich brand → named contacts)
6. **Phase 3b** — Outreach (AI-generated cold pitches via Smartlead)
7. **Phase 4** — Deal lifecycle (LEAD → PROPOSAL → CONTRACT → DELIVERY → CLOSE)
8. **Phase 4.5** — Discovery prep pack (AI brief + agenda + slides for the discovery call)
9. **Phase 4.6** — Proposal pack (AI commercial proposal with hard commercial gate)
10. **Phase 4.7** — Contract pack (AI drafting with merge fields + conditional clauses + hard legal review gate)
11. **Phase 4.8** — Invoice pipeline (post detection + invoice generation)
12. **Phase 4.9** — Performance report
13. **Auto-archive** — closes the loop back to Phase 1.5

The system is currently in the **spec phase**. Code lands at M0 (see `docs/project_plan.md`). The repo today is JSON Schemas + workflow docs + plans.

---

## Where to look first

Before writing code:

1. `README.md` — overview + file index
2. `docs/architecture.md` — backend stack + system diagram + agent topology
3. `docs/project_plan.md` — milestones M0-M17 in dependency order
4. `docs/data_lineage.md` — wiring map (where every field comes from + goes to)
5. `docs/dev_setup.md` — local environment setup

Before writing tests:
- `docs/test_plan.md`

Before changing a schema:
- The schema file in `schemas/`
- The relevant workflow doc in `docs/{phase}_workflow.md`
- `docs/data_lineage.md` to understand consumers

Before adding/editing an endpoint:
- `docs/api_conventions.md` (URL + envelope + errors + idempotency + optimistic concurrency)
- `docs/id_conventions.md` (ID format per record type)

Before writing services:
- `docs/code_conventions.md` (naming + async + exceptions + logging + soft-delete + Decimal + UTC)
- `docs/configuration.md` (env vars)

---

## Locked architectural decisions (don't relitigate)

| Decision | Choice |
|---|---|
| Language | Python 3.12 (exact) |
| Web framework | FastAPI (async) |
| ORM | SQLAlchemy 2.x async |
| Validation | Pydantic 2.x (auto-generated from JSON Schemas) |
| DB | Postgres 16 + pgcrypto for column encryption |
| Cache + queue | Redis 7 |
| Object storage | S3-compatible (MinIO in v0.1) |
| Job orchestration | Celery + Celery Beat (cron) |
| Agent framework | Claude Agent SDK (Python) |
| LLM | Claude Opus 4.7 everywhere (v0.1) |
| Migrations | Alembic |
| Observability | Sentry (errors/perf) + Langfuse (LLM traces) + structlog |
| Test runner | pytest + pytest-asyncio |
| Coverage target | 100% with metric per module type (line / state-transition / contract / LLM eval pass rate) |
| Dependency manager | uv |
| Lint + format | ruff |
| Type-check | pyright (strict) |
| Stub frontend | Vue 3 + Vite + Playwright |
| Deployment v0.1 | Local Docker Compose (127.0.0.1 only) |
| Auth v0.1 | None (single-tenant trusted environment) |
| Auth v2 | TBD; spec at `docs/auth_and_authorization.md` |
| URL versioning | `/api/v1/...` |
| Response envelope | Always `{data, meta, errors}` |
| Pagination | Cursor-based |
| Long-running ops | 202 + task_id + polling |
| Idempotency | `Idempotency-Key` header (Stripe pattern) |
| Concurrency | Optimistic via `If-Match` ETag on versioned resources |
| File uploads | Presigned PUT to S3/MinIO |
| Money | Decimal everywhere |
| Time | UTC + ISO 8601 + `DateTime(timezone=True)` |
| Soft-delete | System-wide (`is_deleted` + `deleted_at` + `deleted_by_agent_id`) |
| ID generation | Server-side; see `docs/id_conventions.md` for per-type formats |
| Pre-commit | Aggressive (lint + format + typecheck + schema codegen drift + unit tests for changed files + trufflehog + JSON schema validation) |

---

## Strict don'ts

- **NEVER** read `os.environ` in domain code. Use `app.config.settings`.
- **NEVER** use `datetime.now()` without `UTC`. Use `datetime.now(UTC)`.
- **NEVER** use `float` for money. Use `Decimal`.
- **NEVER** log PII (legal names, emails, contract clauses, memo content, raw tokens).
- **NEVER** print to stdout in app code. Use `log = structlog.get_logger()`.
- **NEVER** add `Any` type hints in `app/`. Be specific.
- **NEVER** mix async + sync calls in service-layer functions.
- **NEVER** commit secrets (any value for vars listed in `docs/configuration.md` § 5).
- **NEVER** generate IDs ad-hoc; use `app/utils/ids.py` functions.
- **NEVER** hard-delete via API. Soft-delete (`is_deleted = True`).
- **NEVER** raise bare exceptions; use the `NATIV2Error` hierarchy (`app/errors.py`).
- **NEVER** write multi-paragraph docstrings; link to `docs/{workflow}.md` instead.
- **NEVER** write comments restating code; only WHY-comments for non-obvious behaviour.
- **NEVER** add features beyond what the task requires (no premature abstractions; no speculative features).
- **NEVER** modify generated code in `app/models/pydantic/` (it's auto-regenerated from schemas).

---

## Strict dos

- **DO** read the relevant workflow doc before changing a schema or building a phase.
- **DO** add tests in the same PR as the code (no orphan code without tests).
- **DO** bump `template_version` on any change to `agency_profile.invoice_template.*` or `talent.contract_template.*` fields (GAP-07 + GAP-08 enforcement).
- **DO** populate `agency_id` on every domain row even in v0.1 (multi-tenant readiness).
- **DO** filter by `(agency_id, is_deleted == False)` in every repository read.
- **DO** use the `Idempotency-Key` header pattern on all writes per `docs/api_conventions.md` § 6.
- **DO** capture optimistic version via `If-Match` on writes to versioned resources.
- **DO** wrap LLM calls in Langfuse trace spans with `pack_id`, `pack_type`, `subagent_name`, `pass_name` metadata.
- **DO** validate inputs at API boundary via Pydantic; trust internal callers (don't re-validate).
- **DO** raise `NATIV2Error` subclasses from services; let the FastAPI exception handler convert to envelope responses.

---

## Schema discipline

When changing a JSON Schema in `schemas/`:

1. Edit `schemas/{name}.schema.json`.
2. Bump the schema `$id` version if breaking.
3. Re-run `just codegen` to regenerate `app/models/pydantic/`.
4. Update the corresponding SQLAlchemy model in `app/models/sqla/`.
5. Generate an Alembic migration: `uv run alembic revision --autogenerate -m "..."`.
6. Inspect + edit the migration; apply with `just migrate`.
7. Update the corresponding `docs/{phase}_workflow.md` to reflect the change.
8. Update `docs/data_lineage.md` if the field is cross-phase.
9. Add a round-trip test in `tests/integration/test_schema_roundtrip.py`.

Pre-commit catches drift between schemas and Pydantic; CI catches drift between Pydantic and SQLAlchemy via integration tests.

---

## Agent code discipline

Agent code lives in `app/agents/`. Key rules:

- **One coordinator (`DealOrchestratorAgent`) per pack-generation job.** Spawned in a Celery `llm_heavy` task.
- **4 skill subagents** — researcher / writer / extractor / renderer. Each is generic; pack-specific behaviour comes from the coordinator's prompt + context bundle.
- **Context bundle composer** (deterministic; runs BEFORE agent invocation) loads the right blocks per `docs/architecture.md` § 6.
- **Augment tools** (`get_talent`, `get_deal`, `read_memos`, `write_memo`, etc.) live in `app/agents/tools/` — generic + reusable.
- **Memos**: every agent invocation can write memos for cross-deal learning. Tag with `talent_ids[] + brand_ids[] + industry_ids[] + deal_ids[] + topics[] + phase_context`. Retrieval is deterministic tag-filter SQL (no vector embedding in v0.1).
- **Prompt caching**: the static portion of bundles is marked with `cache_control: ephemeral`. 90%+ token reuse across passes in a pack generation.
- **Cost tracking**: every LLM call records (input_tokens, output_tokens, cost_usd) via Langfuse. Daily soft cap = `LLM_BUDGET_DAILY_USD`; hard kill = `LLM_BUDGET_HARD_KILL_DAILY_USD`.
- **Cassette-first tests**: every agent test uses vcrpy cassettes by default. Re-record nightly via `pytest -m llm_eval_record`. Real LLM only runs in nightly CI gated by budget.

---

## Test discipline

- **Cassette LLM** in unit/integration tests (free, fast).
- **Real LLM** only in nightly CI (`pytest -m live_llm`) gated by `$25` budget.
- **Tests live next to code**: `app/services/foo.py` → `tests/unit/services/test_foo.py`.
- **Test naming**: `test_unit__scenario__expected`.
- **Fixtures**: factory_boy in `tests/factories/` per schema. Never construct domain objects via raw dicts in tests.
- **Real fixtures** (real agency + real talent): live in `~/.nativ/test_fixtures/`. Tests with `@requires_real_fixture` marker skip cleanly if absent.

---

## When in doubt

1. Check `docs/{relevant_workflow}.md`.
2. Check `docs/data_lineage.md` for upstream/downstream impact.
3. Check `docs/code_conventions.md` for the right pattern.
4. Search for a similar existing implementation in the codebase.
5. If still unclear, ask in the team channel — don't invent.

---

## Slash commands etc.

If the user types `/code-review` or other Claude Code commands, follow their respective skills. No project-specific commands defined yet; project-specific slash commands land in `.claude/commands/` in v0.2.

---

## Where AI assistants can help most

- **Schema understanding**: tracing fields across phases is tedious; AI is fast.
- **Test fixture construction**: factory_boy boilerplate.
- **State machine completeness**: enumerating valid/invalid transitions.
- **Audit Tier 1/2 fix verification**: cross-referencing schema/workflow/test consistency.
- **Workflow doc edits**: small + many; AI catches stale references quickly.

## Where AI assistants should be careful

- **LLM eval cassette re-records**: ensure the recorded responses are deterministic + don't bake in prompt-injection-style failures.
- **DB migrations**: review every autogenerated Alembic migration carefully; SQLAlchemy autogen misses some cases (e.g. CHECK constraints, GIN indexes).
- **Agent prompts**: prompt changes ripple through cassettes; verify the change is intentional + re-record all affected scenarios.
- **Auth/authz code** (when v2 lands): security-critical; require human review + tests for cross-tenant boundaries.
