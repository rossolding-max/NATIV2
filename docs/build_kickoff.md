# Build Kickoff — NATIV2 v0.1

**From:** Architecture
**To:** Dev team picking up the build
**Date:** 2026-05-27
**Subject:** Pre-build reading + orientation

---

## TL;DR

You're about to build **NATIV2 v0.1** — an AI influencer marketing assistant for talent agencies. **The spec is complete.** Your job is to turn ~22 docs + 17 JSON Schemas into working Python code following the milestone sequence in `docs/project_plan.md`.

Read this memo top-to-bottom (~15 min). Then read the 6 mandatory docs in § 3 (~2 hours). Then start M0.

Everything you need to know about the system lives in `docs/`. Everything you might worry about ("what about auth?", "what about presigned uploads?", "what about industry KPI benchmarks?") is either built into v0.1 or explicitly documented in `docs/v2_deferred_requirements.md`. There are **no TBDs** in the codebase — every design decision is explicit.

---

## 1. The product in 60 seconds

A 12-phase pipeline an agency operator follows to manage influencer marketing deals end-to-end:

```
P0  Agency setup       (one-time per agency)
P1  Talent onboarding  (per talent)
P1.5 Past brand_deals capture
P2  Brand discovery     (16 searches surface candidate brands)
P3a Contact CRM         (enrich brand → named contacts)
P3b Outreach            (AI-generated cold pitches via Smartlead)
P4  Deal lifecycle     (LEAD → PROPOSAL → CONTRACT → DELIVERY → CLOSE)
P4.5 Discovery prep pack    [AI]
P4.6 Proposal pack          [AI]
P4.7 Contract pack          [AI]
P4.8 Invoice pipeline       [AI lightweight]
P4.9 Performance report     [AI]
A   Auto-archive       (closes the loop back to P1.5)
```

5 of the 12 phases involve AI pack generation using a coordinator (`DealOrchestratorAgent`) + 4 skill subagents (researcher / writer / extractor / renderer) wired through the Claude Agent SDK with Anthropic Opus 4.7. Each agent invocation can write/read memos for cross-deal learning.

---

## 2. Where we are right now

Spec phase complete. Repo today:

| Category | Count | Lives in |
|---|---|---|
| Spec docs | 22 | `docs/` |
| JSON Schemas | 17 | `schemas/` (16 domain + 1 shared kpi_metric) |
| Seed data files | 9 | `data/` (industries / niches / brand_industry_map / etc.) |
| Utility scripts | 3 | `scripts/` |
| Dev hygiene files | 7 | `CLAUDE.md`, `CONTRIBUTING.md`, `SECURITY.md`, `.editorconfig`, `.pre-commit-config.yaml`, `.env.example`, `.markdownlint.yaml` |
| Application code | **0** | (M0's job to scaffold) |

---

## 3. Mandatory pre-build reading (in this order)

| # | Doc | What you'll learn | Time |
|---|---|---|---|
| 1 | [`README.md`](../README.md) | What's in the repo + brief description of every doc, schema, and data file | ~20 min |
| 2 | [`CLAUDE.md`](../CLAUDE.md) | 18 locked architectural decisions + 15 strict don'ts + 11 strict dos + schema-change discipline + agent-code discipline | ~15 min |
| 3 | [`docs/architecture.md`](architecture.md) | Stack inventory + ASCII system diagram + 4 skill subagent topology + LLM tier map + memo store + context bundle composition + Celery queue catalog + cron schedule + integration layer + observability + target repo layout | ~30 min |
| 4 | [`docs/project_plan.md`](project_plan.md) | M0-M17 milestone sequence with inputs / outputs / acceptance / skip notes / interdependency checks per milestone | ~30 min |
| 5 | [`docs/data_lineage.md`](data_lineage.md) | ~110 cross-phase data flows with concrete schema paths. **Skim now**, then deep-read the sections relevant to whichever phase you're starting. | ~30 min skim |
| 6 | [`docs/test_plan.md`](test_plan.md) | Test strategy + 11 test categories + per-milestone test deliverables + per-app-phase test deliverables + `nativ test` CLI tool + LLM eval cassette infrastructure | ~20 min |

Total: ~2 hours. You won't internalize everything; these are reference docs. Goal is to know what's there + roughly where to find it.

---

## 4. Read-before-coding triggers

| Before you... | Read |
|---|---|
| Run anything locally | [`docs/dev_setup.md`](dev_setup.md) |
| Touch a schema | The schema file in `schemas/` + the relevant `docs/{phase}_workflow.md` + `docs/data_lineage.md` |
| Add or change an endpoint | [`docs/api_conventions.md`](api_conventions.md) + [`docs/id_conventions.md`](id_conventions.md) |
| Write a service or repository | [`docs/code_conventions.md`](code_conventions.md) |
| Add or change an env var | [`docs/configuration.md`](configuration.md) |
| Implement an AI agent or pack | `docs/architecture.md` § 3-6 + the relevant `docs/{pack}_workflow.md` |
| Write tests for a milestone | `docs/test_plan.md` § 2 (per-milestone) and § 3 (per-phase) |
| Implement auth-related code | [`docs/auth_and_authorization.md`](auth_and_authorization.md) (v0.1 has no auth; document what you assume) |
| Open a PR | [`CONTRIBUTING.md`](../CONTRIBUTING.md) |
| Wonder "what about X?" where X feels deferred | [`docs/v2_deferred_requirements.md`](v2_deferred_requirements.md) — 53 V2-* IDs explicitly catalogued |

---

## 5. Locked decisions — DO NOT relitigate

Full table in `CLAUDE.md`. Highlights:

| Topic | Decision |
|---|---|
| Language | Python 3.12 exact |
| Stack | FastAPI async + SQLAlchemy 2 async + Celery + Postgres 16 + Redis 7 + S3 (MinIO local) |
| LLM | Claude Opus 4.7 everywhere in v0.1 |
| Agent topology | Coordinator + 4 skill subagents (researcher / writer / extractor / renderer) |
| Memo store | Explicit write + tag-filter retrieval (no vector embedding v0.1) |
| Auth v0.1 | **None** — single-tenant local-hosted, FastAPI binds to 127.0.0.1 |
| Multi-tenancy | `agency_id` on every domain schema; repository-layer filtering from day 1 |
| URL versioning | `/api/v1/...` |
| Response shape | Always-envelope `{data, meta, errors}` |
| Pagination | Offset v0.1 (`?page=1&page_size=50`); cursor v2 |
| Long-running ops | 202 + task_id + polling (`/api/v1/tasks/{id}`) |
| Idempotency | `Idempotency-Key` header required on POST creates + `:action` endpoints; optional on PATCH/DELETE |
| Concurrency | Last-write-wins v0.1; If-Match v2 |
| File uploads | Multipart through FastAPI v0.1; presigned PUT v2 |
| ID generation | Server-side; see `docs/id_conventions.md` for per-type formats |
| Money | Decimal everywhere; `Numeric(precision=12, scale=2)` |
| Time | UTC + ISO 8601 + `DateTime(timezone=True)` |
| Soft-delete | System-wide (`is_deleted` + `deleted_at` + `deleted_by_agent_id`) via `SoftDeleteMixin` |
| Celery queues | 2 (`default` + `llm_heavy`) v0.1; 4 v2 |
| Test coverage | 100% with metric per module type (line / state-transition / contract / LLM eval pass rate) |
| Stub frontend | **None v0.1** — schemathesis property-based tests for API contract |
| Pre-commit | Aggressive (ruff + ruff format + pyright strict + trufflehog + schema codegen drift + unit tests for changed files + JSON Schema validation) |

If you find yourself wanting to change one of these, open a team-channel discussion BEFORE coding a PR.

---

## 6. Your first week

| Day | What |
|---|---|
| **Day 1** | Read § 3 mandatory docs. Set up local environment per `docs/dev_setup.md`. Pair with someone on `git log --oneline` to walk the spec history (you'll see how decisions evolved). |
| **Day 2** | Begin M0 — repo foundation. `pyproject.toml`, `docker-compose.yml`, `justfile`, Alembic init, FastAPI `app/main.py` skeleton with health endpoint + Sentry init, `app/celery_app.py` with 2 queues. |
| **Day 3** | Continue M0. `tests/conftest.py` with testcontainers Postgres + Redis + MinIO. `tests/factories/` factory_boy stubs. `.github/workflows/test.yml` + `.pre-commit-config.yaml` integrated. |
| **Day 4** | Finish M0. Open PR. `docker compose up && pytest tests/` passes; CI green. |
| **Day 5** | Begin M1 — data layer. Auto-generate Pydantic from 17 schemas via `datamodel-code-generator`; hand-write SQLAlchemy models. Alembic migration applying all tables + pgcrypto + GIN indexes. |

PRs should be focused and small. A single milestone may span 5-15 PRs depending on scope.

---

## 7. Critical rules to internalize

These exist for reasons explained elsewhere; you'll absorb them as you go but knowing them upfront prevents painful refactors:

1. **`agency_id` flows through everything.** Repository layer filters by it automatically — DON'T write SQL that skips this. Even v0.1 with one agency, the discipline is in place from day 1 (it's the v2 multi-tenant bridge).
2. **Schema-Pydantic-SQLAlchemy round-trip.** Edit `schemas/{entity}.schema.json` → `just codegen` regenerates `app/models/pydantic/{entity}.py` → you hand-write `app/models/sqla/{entity}.py` → Alembic autogenerate the migration → review it carefully (autogen misses CHECK constraints + GIN indexes).
3. **Memos are the agent memory.** Any subagent can write a memo at any time. Read them via `read_memos(...)` with tag filters. Each milestone that involves agent code must document what memos it writes + reads.
4. **Pack pipelines have hard gates.** Commercial gate in Phase 4.6 — slides cannot render until agent confirms. Legal review gate in Phase 4.7 — contract cannot finalise until reviewer approves. These are not optional UX flourishes; they're enforced server-side.
5. **Idempotency-Key on creates + actions.** `POST /resource` + `POST */:action` MUST carry it. Server stores `(key, agency_id, response)` for 24h (7d for pack-gen kickoffs). Replays return the original response.
6. **Long-running ops return 202 + task_id.** Never block on a 30-90s pack generation. Frontend polls `/api/v1/tasks/{id}` every 2-5s.
7. **All ID generation goes through `app/utils/ids.py`.** No ad-hoc UUIDs or slugs anywhere in app code.
8. **No PII in logs.** Pre-commit catches obvious cases; review your own logs in PR.

---

## 8. Common pitfalls (specifically designed to prevent — don't reintroduce)

| ❌ Do not | ✅ Do |
|---|---|
| Read `os.environ` directly | Use `app.config.settings.foo` |
| `datetime.now()` without UTC | `datetime.now(UTC)` (ruff DTZ blocks the bad form) |
| `float` for monetary values | `Decimal` always |
| `print()` in app code | `log = structlog.get_logger()` then `log.info(...)` |
| Hard-delete via API | Soft-delete (set `is_deleted = True`) |
| Generate IDs ad-hoc | Use functions in `app/utils/ids.py` |
| Multi-paragraph docstrings | Link to `docs/{workflow}.md` |
| Comments restating code | Self-documenting names |
| Modify `app/models/pydantic/` | It's auto-regenerated; edit schemas instead |
| Bare `except:` | `except SpecificError:` or `except NATIV2Error:` |
| Mix sync + async in service layer | Pick one per function |

Full 15-item list: `CLAUDE.md` § "Strict don'ts".

---

## 9. Where the v2 stuff lives

If you find yourself thinking "shouldn't we have X?" — search `docs/v2_deferred_requirements.md`. 53 V2-* IDs across 11 categories. Every deferral includes:

- **What v0.1 does instead** (the simpler behaviour you'll build)
- **What v2 will add** (eventually)
- **Where the v0.1 code reflects the deferred behaviour** (so v2 work has a clear seam)
- **v2 cost estimate**

Common "what about" items already documented:

- Auth + login + JWT → V2-AUTH-01
- Optimistic concurrency → V2-API-01
- Cursor pagination → V2-API-02
- Presigned PUT uploads → V2-STORAGE-01
- pgvector semantic memo retrieval → V2-STORAGE-04
- 4-queue Celery split → V2-SCALE-01
- Prep pack slide rendering (HTML/PDF/PPTX) → V2-PACK-01
- Sibling commission invoice auto-gen → V2-PACK-02
- Industry KPI benchmarks → V2-PACK-04
- Stub frontend → V2-FRONT-01
- Stripe invoice automation → V2-VENDOR-01
- DocuSign contract automation → V2-VENDOR-02
- Phyllo for non-Meta/TikTok detection → V2-VENDOR-03
- GDPR right-to-erasure → V2-OPS-03

If your "what about" isn't covered: ask in team channel.

---

## 10. Where to ask questions

| Question type | Where |
|---|---|
| "How should I do X?" | `docs/code_conventions.md` first; team channel if not covered |
| "Why is the spec like this?" | `git log` on the relevant doc — spec history is preserved |
| "Has decision X been made?" | `CLAUDE.md` locked decisions table |
| "Is X scheduled for v0.1 or v2?" | `docs/v2_deferred_requirements.md` |
| "How does X flow through the system?" | `docs/data_lineage.md` |
| Schema clarification | Open issue tagged `spec/schema/{schema-name}` |
| Security concern | Per `SECURITY.md` — private channel only |
| Stuck on a phase | The relevant `docs/{phase}_workflow.md` is authoritative |

---

## 11. Self-test — you've finished reading when you can answer

If you can answer all 12 from memory (no peeking), you're oriented enough to start M0. Miss any → re-skim the relevant doc.

1. What are the 4 skill subagents and what does each do?
2. Where does `agency_id` come from on every API request in v0.1?
3. What's the difference between Phase 4.5 prep pack output in v0.1 vs v2?
4. Which 3 conditions trigger auto-archive (Phase 4 → Phase 1.5 loop closure)?
5. Why doesn't v0.1 implement optimistic concurrency (If-Match)?
6. Where is the canonical `kpiMetric` schema definition?
7. What's the difference between `brand_candidate.candidates[].pitch_history[]` (legacy) and `pitch_enrollment.*` (canonical)?
8. Where do REAL (vs synthetic) test fixtures live?
9. What endpoints require an `Idempotency-Key` header in v0.1?
10. Which Anthropic model does v0.1 use?
11. What's the difference between `deal_id` formats for active deals vs archived deals?
12. Where do agents write memos + what tag system do they use?

Answers are in the docs. Don't ask anyone for the answers; find them yourself — the act of finding them teaches you the doc structure.

---

## 12. Pre-PR checklist

Before opening your first PR:

- [ ] I have read all 6 mandatory docs in § 3
- [ ] I have set up my local environment per `docs/dev_setup.md` (or know I will when M0 ships the scaffolding)
- [ ] I have read `docs/code_conventions.md` end-to-end
- [ ] I have read `docs/api_conventions.md` § 1-12
- [ ] I have read `CONTRIBUTING.md` PR + branch + commit message sections
- [ ] I have installed pre-commit hooks: `uv run pre-commit install`
- [ ] I have skimmed `docs/v2_deferred_requirements.md` table of contents (so I know what's NOT in v0.1)
- [ ] I know which milestone I'm working on + its acceptance criteria
- [ ] I know which workflow doc(s) my changes touch
- [ ] I have written + passed tests for the change (per `docs/test_plan.md` for the relevant milestone)
- [ ] My commit messages explain WHY (not just WHAT)

When all 11 ticked: you're ready.

---

## 13. One more thing

The codebase is ~30 docs of spec for a reason — the system is genuinely intricate (12 phases, 5 AI pack types, cross-phase data dependencies, multi-vendor integrations, hard gates, multi-tenant readiness). Don't be intimidated; lean on the docs.

The audit found exactly **0 broken cross-phase dependencies** + **0 unspecified design decisions**. Anything that feels missing is in `docs/v2_deferred_requirements.md`. Anything that feels under-specified is in `docs/code_conventions.md` + `docs/api_conventions.md`.

If you find a genuine gap: that's a real find. Open an issue tagged `spec/gap` with the question + your reasoning.

---

Welcome. Build well.

— Architecture
