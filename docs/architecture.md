# Backend Architecture Specification

**Status:** Locked v0.1 (2026-05-26). Decisions captured via the interview process; rationale + alternatives in commit history. Pairs with `docs/project_plan.md` (dependency-ordered milestones).

**Scope:** backend only. Frontend architecture deferred to a separate spec when the UI work begins.

---

## 1. Stack inventory

| Layer | Choice |
|---|---|
| Language | **Python 3.12+** |
| Web framework | **FastAPI** (async) |
| Async orchestration | **Celery** (Redis broker) + **Celery Beat** for cron |
| Database | **PostgreSQL 16+** |
| Cache + queue | **Redis 7+** |
| Object storage | **S3-compatible** (MinIO in local v0.1; AWS S3 / GCS in production) |
| Migrations | **Alembic** |
| ORM | **SQLAlchemy 2.x** (hand-written models, async) |
| Validation | **Pydantic 2.x** (auto-generated from JSON schemas via `datamodel-code-generator`) |
| Secrets at rest | **pgcrypto** column-level AES-256 |
| Agent framework | **Claude Agent SDK (Python)** |
| LLM | **Claude Opus 4.7 everywhere** (quality-optimised; ~$1.50-3 per pack) |
| File parsing | **pypdf**, **python-docx** |
| Rendering | **Jinja2** (HTML/markdown templates) + **Playwright** via `playwright-python` (PDF rendering — drives headless Chromium) + **python-docx** (Word output) |
| Email outbound | **Smartlead API** (Phase 3b cold outreach); **Postmark or Resend** for transactional (system notifications to agent) |
| Vector DB | **None in v0.1** (tag-filter memos only); pgvector deferred to v0.2 |
| Errors / perf | **Sentry** (Python SDK) |
| LLM observability | **Langfuse** (self-hosted in local v0.1; cloud later) |
| Test | **pytest** + **pytest-asyncio** + **factory_boy** + **respx** (HTTP mocking) + **schemathesis** (OpenAPI contract testing) |
| Local infra | **Docker Compose** (FastAPI + Celery worker + Celery beat + Postgres + Redis + MinIO + Langfuse) |
| Deployment | **Local hosted v0.1**; production hosting decision deferred to v2 |
| API protocol — v0.1 | Offset pagination; multipart uploads through FastAPI; last-write-wins on writes; `Idempotency-Key` on POST creates + `:action` endpoints |
| API protocol — v2 deferrals | Cursor pagination, presigned PUT, optimistic `If-Match` concurrency, SSE pack-progress streaming. See `docs/v2_deferred_requirements.md` § 2 |
| Frontend smoke (v0.1) | None — production frontend deferred entirely. API readiness validated via OpenAPI contract tests (schemathesis property-based) |

## 2. System architecture (component diagram)

```
                          ┌─────────────────────────────────┐
                          │ HTTP API layer (FastAPI)        │
                          │   - /agencies, /talents,        │
                          │     /deals, /packs/*             │
                          │   - Webhook endpoints            │
                          │     (Smartlead, Stripe v2,       │
                          │     DocuSign v2, Meta, TikTok)   │
                          └────────────────┬────────────────┘
                                           │
              ┌────────────────────────────┼─────────────────────────────┐
              │                            │                              │
              ▼                            ▼                              ▼
    ┌──────────────────┐         ┌──────────────────┐         ┌──────────────────┐
    │ Domain services  │         │ Agent coordinator│         │ Job dispatcher   │
    │ (business logic, │         │ (Claude Agent    │         │ (Celery client)  │
    │  state machines) │         │  SDK orchestrator│         │                  │
    └────────┬─────────┘         └────────┬─────────┘         └────────┬─────────┘
             │                            │                            │
             │                            │                            │
             ▼                            ▼                            ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │ Skill subagents (Claude Agent SDK subagents — Opus 4.7)              │
    │                                                                       │
    │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────────┐ │
    │  │ researcher │  │   writer   │  │ extractor  │  │    renderer    │ │
    │  │  - Exa     │  │  - drafts  │  │  - pypdf   │  │  - Jinja2 HTML │ │
    │  │  - web     │  │    with    │  │  - python- │  │  - Playwright   │ │
    │  │    search  │  │    sources │  │    docx    │  │    PDF         │ │
    │  │  - read    │  │  - cites   │  │  - LLM     │  │  - python-docx │ │
    │  │    brand_  │  │    sources │  │    summary │  │    Word        │ │
    │  │    industry│  │  - editable│  │  - signal  │  │  - apply       │ │
    │  │    _map    │  │    in      │  │    extract │  │    agency      │ │
    │  │  - read    │  │    place   │  │  - confi-  │  │    branding    │ │
    │  │    memos   │  │            │  │    dence   │  │                │ │
    │  └────────────┘  └────────────┘  └────────────┘  └────────────────┘ │
    │                                                                       │
    │  Shared tool catalog: get_talent, get_deal, get_brand_record,        │
    │  get_brand_deals_filtered, get_top_angles, write_memo, read_memos,    │
    │  validate_schema, render_template, ...                                │
    └──────────────────────┬───────────────────────────────────────────────┘
                           │
              ┌────────────┼─────────────┐
              ▼            ▼             ▼
       ┌──────────┐  ┌──────────┐  ┌──────────┐
       │ Postgres │  │  Redis   │  │   S3     │
       │ (state + │  │ (queue + │  │ (uploads │
       │  memos + │  │  cache + │  │  + packs │
       │  schemas)│  │   pub/   │  │  + arte- │
       │          │  │   sub)   │  │  facts)  │
       └──────────┘  └──────────┘  └──────────┘

       Observability sidecar:
         - Sentry (Python SDK in every process)
         - Langfuse (LLM call tracing; multi-agent span stitching)
```

## 3. Agent topology (coordinator + skill specialists)

**Top-level coordinator:** `deal_orchestrator_agent`. One instance spawned per active pack-generation job. Holds the deal's full state in working context (loaded via context bundle).

**4 skill specialists** (subagents):

| Agent | Tools | Use cases |
|---|---|---|
| **researcher** | Exa search, web fetch, `get_brand_record`, `get_brand_deals_filtered`, `get_top_pitch_angles`, `read_memos(scope=brand_relationship/industry_pattern)` | Brand context for prep pack; debrief extraction prep; case-study selection; benchmark-comparison research |
| **writer** | `read_memos`, `get_talent`, `get_deal`, `render_template`, `write_memo` (for learnings) | All narrative drafting: briefing notes, agenda, slide bodies, contract narratives, invoice line items, performance report narrative |
| **extractor** | pypdf, python-docx, text reader, `write_memo` (for extracted patterns) | Parse uploaded briefs/notes/transcripts/redlines; populate context_artefacts; extract structured fields (discovery_debrief, brand legal info, brand redlines) |
| **renderer** | Jinja2, Playwright, python-docx, `get_agency_profile` (for branding) | Compose markdown → HTML / PDF / DOCX. Apply agency branding. No LLM calls — deterministic only. |

**Why this shape:** the 5 pack types (prep / proposal / contract / invoice / performance report) all share these 4 skills with different compositions. Skill agents stay generic; coordinator + pack-specific prompts make them context-aware.

**Pack-to-skill composition map:**

| Pack | researcher | extractor | writer | renderer |
|---|---|---|---|---|
| **Prep (4.5)** | ✅ heavy (Exa brand research) | — | ✅ briefing + agenda + slide markdown | **deferred to v2** (V2-PACK-01) — v0.1 ships markdown only |
| **Proposal (4.6)** | medium | ✅ heavy (debrief from uploads) | ✅ slides + recommendation | ✅ (first pack to engage renderer) |
| **Contract (4.7)** | — | ✅ (brand legal uploads) | ✅ merge + clauses + narrative | ✅ |
| **Invoice (4.8)** | — | — | ✅ light (line items only) | ✅ |
| **Performance Report (4.9)** | ✅ (vs_talent_historical benchmarks; vs_industry deferred to V2-PACK-04) | — | ✅ narrative (exec summary, learnings) | ✅ |

## 4. LLM tier map

**All Opus 4.7** for v0.1 per locked decision. Future cost-optimisation paths documented for v0.2 review:

| Task | v0.1 model | v0.2 candidate downgrade if budget pressure |
|---|---|---|
| Prep pack briefing/agenda/slides | Opus 4.7 | Sonnet 4.6 (-80% cost) |
| Proposal slides | Opus 4.7 | Sonnet 4.6 |
| Discovery debrief extraction | Opus 4.7 | Stays Opus (high-stakes) |
| Contract narrative + clause evaluation | Opus 4.7 | Stays Opus (legal stakes) |
| Invoice line-item descriptions | Opus 4.7 | Haiku 4.5 (-95% cost; low-stakes) |
| Performance report narrative | Opus 4.7 | Sonnet 4.6 |
| Phase 3b reply classification | Opus 4.7 | Haiku 4.5 |
| Phase 4.8 post-match scoring | n/a (deterministic) | n/a |
| Payment terms LLM parse | Opus 4.7 | Stays Opus (commercial stakes) |
| Brand legal info extraction from uploads | Opus 4.7 | Sonnet 4.6 |
| Decision_role tagging | Opus 4.7 | Haiku 4.5 |

## 5. Memo store

Cross-invocation, cross-deal, cross-brand, cross-industry memory for agents. Validated against `schemas/memo.schema.json`.

**Schema highlights:**
- `scope` enum: deal_specific / brand_relationship / industry_pattern / talent_pattern / cross_cutting
- `memo_type` enum: deal_summary / brand_observation / negotiation_pattern / kpi_pattern / objection_handler / creative_insight / talent_learning / industry_insight / agent_decision_audit / other
- `tags`: structured FK tags (talent_ids / brand_ids / industry_ids / deal_ids / topics) + phase_context enum
- `content_markdown`: primary narrative; optional `structured` JSON for typed payloads
- Lifecycle: `supersedes_memo_id` chain + `expires_at` TTL + `is_active` soft-delete + `retrieval_count` + `last_retrieved_at` audit

**Retrieval (`read_memos` tool):**
```python
read_memos(
    talent_id: str | None = None,
    brand_id: str | None = None,
    industry_id: str | None = None,
    deal_id: str | None = None,
    topics: list[str] | None = None,
    scope: list[Scope] | None = None,
    memo_type: list[MemoType] | None = None,
    limit: int = 20,
    sort: "recency" | "specificity" = "specificity"
)
```

Multiple values per tag = OR; multiple tag keys = AND. v0.1 = deterministic tag-filter SQL queries (no vector embedding). v0.2 may add pgvector for semantic search within tag-filtered subsets.

**Write (`write_memo` tool):** any subagent can write at any time. Coordinator can also explicitly summarise on key transitions (deal won/lost; brand pushback; first deal in industry).

**Cross-deal queries:** when prepping a proposal for a competitor of a past brand, researcher calls `read_memos(brand_id=competitor_brand, industry_id=same_industry, scope=["brand_relationship", "industry_pattern"])` — surfaces relevant patterns from prior deals automatically.

**Postgres table:** `memo` row per memo. Indexed on `(agency_id, created_at)` + GIN indexes on `tags` JSONB columns + scope/memo_type. Content >32kB optionally offloaded to S3 with `content_markdown_s3_key` field (v0.2; v0.1 always inline).

## 6. Context loading (hybrid bundle + augment)

**Per-pack context bundle composer** runs deterministically before agent invocation. Components included per pack:

| Bundle component | All packs | Prep | Proposal | Contract | Invoice | Perf Report |
|---|---|---|---|---|---|---|
| `talent_profile` (~5-15k tok) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `agency_profile` (incl. branding) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `deal_record` (full) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `brand_record` (industry_map entry) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `brand_contact` (primary) | ✅ | ✅ | ✅ | — | — | — |
| `comparable_brand_deals[]` (top 5) | | ✅ | ✅ | — | — | ✅ |
| `top_pitch_angles[]` (for brand×niche) | | ✅ | ✅ | — | — | — |
| `originating_enrollment` (full) | | ✅ | — | — | — | — |
| `discovery_debrief` (when populated) | | — | ✅ | ✅ | — | ✅ |
| `proposal_pack` (latest) | | — | — | ✅ | ✅ | ✅ |
| `contract_pack` (latest) | | — | — | — | ✅ | ✅ |
| `posting_schedule + interim_kpi_snapshots` | | — | — | — | ✅ | ✅ |
| `relevant_memos[]` (auto-loaded via tag filters) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

**Augment tools** (agent calls when bundle insufficient):
- `get_full_brand_deals_for_talent(talent_id)`
- `get_brand_deals_for_brand_across_talents(brand_id)`
- `get_full_brand_industry_map_filtered(industry_id, limit)`
- `get_full_originating_enrollment(enrollment_id)`
- `get_context_artefact(artefact_id)` (full parsed text)
- `read_memos(...)` (see § 5)
- `web_search(query)` / `exa_search(query, category)` (researcher only)

**Prompt caching:** the static portion of bundles (talent_profile + agency_profile + brand_record) is identical across the 3-5 LLM passes within a single pack generation. The Claude Agent SDK + Anthropic API supports prompt caching natively — the orchestrator marks the static prefix as `cache_control: ephemeral` and 90%+ of bundle tokens reuse across passes.

## 7. Data layer

### Postgres schema strategy

- **One database** in v0.1; multi-tenant-ready via `agency_id` UUID column on every domain table (even though v0.1 has one agency).
- Tables named in singular (`talent`, `deal`, `brand_candidate`, etc.) per SQLAlchemy convention.
- Per-pack JSONB columns for the structured payload (e.g. `deal.lead`, `deal.proposal`, `deal.contract`, `deal.delivery`, `deal.close` each stored as JSONB on the `deal` row) — fast read with `jsonb_path_ops` GIN indexes; preserves the schema-aligned shape.
- **Indexes:** `(agency_id, talent_id)` on every per-talent table; `(deal_id, version)` on pack tables; GIN indexes on memo tags + JSONB.
- **Encryption:** `pgcrypto` extension. Sensitive columns (oAuth tokens, API keys, contract clauses with NDA content): wrapped in `pgp_sym_encrypt(value, master_key)`. Master key from env (`DB_MASTER_KEY`).
- **Migrations:** Alembic; one revision per schema change. Schema changes also bump the corresponding `schemas/*.schema.json` $id version.

### S3 storage layout

```
{bucket}/
  agencies/{agency_id}/
    branding/                    # logo, dark logo
    contract_template_starters/

  talents/{talent_id}/
    headshots/
    media_pack/
    contract_template_versions/  # versioned template snapshots

  deals/{deal_id}/
    prep_packs/v{N}/
      deck-live.html
      deck-leave-behind.pdf
      speaker-notes.md
    proposal_packs/v{N}/
    contract_packs/v{N}/
    invoice_packs/seq{M}_v{N}/
    performance_report_packs/v{N}/
    context_uploads/             # agent-uploaded briefs/notes/transcripts/redlines

  memos/{memo_id}/               # v0.2: large memo attachments
```

S3 paths stored as `s3://{bucket}/{key}` strings in Postgres; presigned URLs minted on read.

### Redis usage

- **Celery broker** (job queue persistence)
- **Cache** for frequently-read read-only data (brand_industry_map, industries, niches, pitch_angles)
- **Pub/sub** for real-time agent-progress streaming (v0.2 when frontend ships)
- **Rate limit counters** for vendor API quotas (Anthropic, Meta Graph, TikTok)

## 8. Job orchestration (Celery queue catalog)

**Queues** (v0.1 = 2 queues; v2 splits to 4 — see `docs/v2_deferred_requirements.md` V2-SCALE-01):

| Queue | Worker type | Tasks |
|---|---|---|
| `default` | General-purpose | Pack gen kickoff; webhook handlers; CRUD-adjacent jobs; vendor API polls (Meta / TikTok / Apollo / Exa); rendering (Playwright PDF; python-docx Word; Jinja2 HTML) |
| `llm_heavy` | Long-running (timeout=30min) | Multi-pass LLM generation jobs (prep/proposal/contract/perf report packs) |

Rate-limit enforcement happens at the vendor-wrapper layer (Redis-backed counters per vendor) regardless of which queue invokes them. v2 splits to `vendor_apis` + `rendering` as separate queues for throughput tuning; v0.1 throughput on a single agency is trivially served by one general queue.

**Scheduled jobs (Celery Beat):**

| Job | Schedule | Description |
|---|---|---|
| `poll_phase_4_8_detection_stories` | every 15min | Poll Meta Graph for IG stories on active DELIVERY deals |
| `poll_phase_4_8_detection_other` | every 1hr | Poll Meta Graph + TikTok for non-story formats |
| `poll_phase_4_9_kpi_capture` | daily 02:00 | Poll Insights APIs for all `posting_schedule` URLs with `posted_at` set + window not yet ended; write to `interim_kpi_snapshots[]` |
| `invoice_overdue_reminders` | daily 09:00 | Find sent invoices with due_at < now; append to `payment_reminder_log`; notify agent |
| `talent_stats_refresh` | weekly Sun 03:00 | Refresh `talent.platforms[].stats.*` for active talents |
| `brand_handle_refresh` | weekly Sun 04:00 | Re-fetch `brand_industry_map.brands[].social_handles` via Exa to detect rebrands |
| `discovery_run` | monthly (per talent) | Phase 2 brand discovery long-list refresh |
| `enrollment_state_sync` | every 5min | Sync Smartlead enrollment states; classify replies; trigger deal creation on `interested` |
| `auto_archive_trigger_check` | every 15min | Find deals where all_invoices_paid_at + final_kpis + final_report all set; fire archive |
| `phase_4_5_auto_fire` | every 5min | Find deals transitioning to `initial_call_scheduled`; fire prep pack generation |

## 9. Phase skip handling

Every phase tolerates missing upstream data with documented degraded behaviour. The agent UI shows skip-handling warnings on affected downstream artefacts.

| If skipped | Downstream behaviour |
|---|---|
| **Phase 1.5** (brand_deals history) | Discovery prep pack lacks comparable case studies → omits "Recent work" slide with note; commercial range computed from industry benchmarks only |
| **Phase 2** (discovery) | Agent manually enters brand_id when creating outreach enrollment; brand_candidate record created on-the-fly with minimal data |
| **Phase 3a** (contact enrichment) | Agent manually enters contact details when creating enrollment; `decision_role` defaulted `unknown` |
| **Phase 3b** (outreach) | Agent manually creates Phase 4 deal in LEAD; `originating_enrollment_id` null |
| **Phase 4.5** (prep pack) | Discovery call notes captured manually in `deal.lead.discovery_call_notes`; agent goes into call without auto-drafted pack |
| **Phase 4.6** (proposal pack) | Agent uploads their own proposal PDF as `deal.proposal.proposal_attachment_id`; commercial fields entered manually |
| **Phase 4.7** (contract pack) | Agent uploads signed PDF directly; `draft_contract_attachment_id` never set; signed timestamps manual |
| **Phase 4.8** (detection) | Agent enters post URLs manually; `posted_detection.method = "manual_url_entry"`; invoice schedule fires on trigger conditions same as before |
| **Phase 4.8** (invoice gen) | Agent uploads invoice PDF manually; `invoice_pack_ids[]` may be empty; `payment_received_at` set manually |
| **Phase 4.9** (perf report) | Agent uploads report PDF manually; `final_kpis` entered manually via UI form; auto-archive can still fire |

## 10. Integration layer

**Vendor wrappers** (one Python module per vendor under `app/vendors/`):

| Vendor | Module | Used by | Auth | Key endpoints |
|---|---|---|---|---|
| **Anthropic** | `app/agents/llm_client.py` (M2; not under `app/vendors/`) | All agents | `ANTHROPIC_API_KEY` | Messages API + prompt caching |
| **Smartlead** | `app/vendors/smartlead.py` | Phase 0 + 3b | `SMARTLEAD_API_KEY` (query string, not header) + `SMARTLEAD_WEBHOOK_SECRET` | campaigns / leads / sequences / webhooks |
| **Exa** | `app/vendors/exa.py` | researcher subagent + Phase 2 | `EXA_API_KEY` | `/search`, `/findSimilar`, `/contents` |
| **Apollo** | `app/vendors/apollo.py` | Phase 3a | `APOLLO_API_KEY` | people search / match / org enrich |
| **LinkedIn (RapidAPI)** | `app/vendors/linkedin.py` | Phase 3a enrichment | `RAPIDAPI_KEY` (RapidAPI gateway; host `linkedin-data-api.p.rapidapi.com` hard-coded) | profile / company-by-domain / recent-posts |
| **Meta Graph** | `app/vendors/meta_graph.py` | Phase 4.8 + 4.9 | `META_APP_ID` + `META_APP_SECRET` + per-talent OAuth (Instagram-Login flow, scopes `instagram_business_*`) | `/me/media`, `/{ig-media-id}/insights`, `/me/stories`; webhooks via `X-Hub-Signature-256` |
| **TikTok Display** | `app/vendors/tiktok.py` | Phase 4.8 + 4.9 | `TIKTOK_CLIENT_KEY` + `TIKTOK_CLIENT_SECRET` + per-talent OAuth **with PKCE** (S256) | `/v2/video/list/`, `/v2/video/query/`, `/v2/user/info/` |

**M3 implementation notes (build-time decisions):**
- All vendor clients inherit from `BaseVendorClient` (`app/vendors/_base.py`) which centralises Sentry breadcrumbs + structlog `vendor_call` events + the `IntegrationError` family mapping (timeout / 429 with `Retry-After` / 4xx / 5xx).
- Retry policy is shared via `app/vendors/_retry.py` (tenacity-based). Retries on connect timeouts, 5xx, and 429 (honours `Retry-After`); skips permanent 4xx.
- Rate limiting is shared via `app/vendors/_rate_limiter.py` — Redis DB 2 token-bucket Lua script (`REDIS_DB_RATELIMIT=2`, reserved in M0; first used by M3).
- Webhook HMAC verification (Smartlead + Meta) is shared via `app/vendors/_webhook_signing.py`.
- OAuth state + PKCE persistence is shared via `app/vendors/_oauth_state.py` — Redis DB 2 with single-use TTL=10min state values. FastAPI callback routes at `/api/v1/webhooks/{meta,tiktok}/oauth_callback` are **live as of M5** and persist exchanged tokens into the `talent_vault` table (per-talent + per-platform composite PK, column-level pgcrypto via `EncryptedString`). The callback also stamps `talent.data.platforms[N].api_credentials.scope_validated_at` after a lightweight read-call confirms the granted scopes work.

**Webhook receivers** (FastAPI endpoints under `/webhooks/{vendor}`):

| Endpoint | Source | Action |
|---|---|---|
| `POST /webhooks/smartlead/email_event` | Smartlead | Engagement events → write to `pitch_enrollment.steps[].engagement_events[]` |
| `POST /webhooks/smartlead/reply` | Smartlead | Reply received → enqueue classification job → on `interested` create Phase 4 deal |
| `GET /api/v1/webhooks/meta/oauth_callback` | Meta Login | OAuth code exchange → write encrypted token + scopes into `talent_vault` + mirror connection state into `talent.data.platforms[]`; lightweight `GET /me/media?limit=1` validates scope, stamps `scope_validated_at` |
| `GET /api/v1/webhooks/tiktok/oauth_callback` | TikTok | Same pattern with PKCE verifier (TikTok required) |
| `POST /webhooks/stripe/invoice_paid` (v2) | Stripe | Auto-populate `invoice_pack.payment_state` |

All webhooks validate signature/HMAC before processing.

## 11. Observability instrumentation

**Sentry:**
- Init in FastAPI app + every Celery worker
- Auto-instrument SQLAlchemy queries, Redis, HTTP requests
- Custom tags: `agency_id`, `talent_id`, `deal_id`, `pack_type`, `pack_id`
- Performance traces enabled

**Langfuse:**
- Wrap every Claude Agent SDK call via Langfuse's Anthropic integration
- One Langfuse `trace` per pack generation job; spans per subagent invocation
- Capture: prompt + completion + tokens (input/output/cached) + cost USD + duration
- Attach metadata: `pack_id`, `pack_version`, `pack_type`, `deal_id`, `subagent_name`, `pass_name`
- Self-hosted via Docker Compose in v0.1 (so it works locally); cloud Langfuse for production v0.2

**Structured logging:**
- `structlog` with JSON output
- Log levels: DEBUG (dev), INFO (default), WARN, ERROR
- Correlation IDs propagated via Celery task headers

## 12. Schema-to-code pipeline

```
schemas/*.schema.json
         │
         │ datamodel-code-generator (CI step)
         ▼
app/models/pydantic/*.py            ← AUTO-GENERATED (don't edit)
         │
         │ hand-authored references
         ▼
app/models/sqla/*.py                ← HAND-WRITTEN SQLAlchemy
         │                            uses Pydantic for JSONB column types
         │
         ▼
alembic/versions/*.py               ← HAND-WRITTEN migrations
                                      generated from SQLAlchemy diffs +
                                      reviewed before apply
```

**Discipline:**
- Schema change PR must include both the JSON Schema edit AND the SQLAlchemy migration
- CI runs `datamodel-code-generator` on every PR; commits a diff if Pydantic models out of sync
- Test fixture: every Pydantic-validated payload round-trips through JSON Schema validation in unit tests (belt-and-braces)

## 13. Repository layout (target)

```
NATIV2/
├── schemas/                      # JSON Schemas (existing — source of truth)
├── docs/                         # Workflow docs + architecture (existing)
├── data/                         # Sample / seed data (industries, niches, etc.)
├── app/                          # NEW — the FastAPI app
│   ├── main.py                   # FastAPI app + Sentry init
│   ├── celery_app.py             # Celery client + Beat schedule
│   ├── config.py                 # Settings via pydantic-settings
│   ├── db/                       # Postgres session + base classes
│   │   ├── session.py
│   │   └── base.py
│   ├── models/
│   │   ├── pydantic/             # auto-generated from schemas
│   │   └── sqla/                 # hand-written ORM
│   ├── repositories/             # async CRUD per model
│   ├── services/                 # business logic (state machines, etc.)
│   ├── agents/                   # Claude Agent SDK code
│   │   ├── base.py               # base Agent class
│   │   ├── coordinator.py        # deal_orchestrator_agent
│   │   ├── skills/               # researcher, writer, extractor, renderer
│   │   ├── tools/                # shared tool catalog
│   │   ├── bundles.py            # context bundle composers
│   │   └── packs/                # per-pack coordinator subclasses
│   ├── api/                      # FastAPI routes
│   │   ├── agencies.py
│   │   ├── talents.py
│   │   ├── deals.py
│   │   ├── packs.py
│   │   ├── memos.py
│   │   └── webhooks/             # vendor webhook receivers
│   ├── vendors/                  # external API wrappers
│   │   ├── anthropic_client.py
│   │   ├── smartlead.py
│   │   ├── exa.py
│   │   ├── apollo.py
│   │   ├── linkedin.py
│   │   ├── meta_graph.py
│   │   └── tiktok.py
│   ├── tasks/                    # Celery task definitions
│   ├── utils/
│   │   ├── encryption.py         # pgcrypto wrappers
│   │   ├── s3.py                 # presigned URL minting
│   │   └── logging.py            # structlog config
│   └── observability/
│       ├── sentry.py
│       └── langfuse.py
├── alembic/                      # NEW — DB migrations
│   ├── env.py
│   └── versions/
├── tests/                        # NEW
│   ├── unit/
│   ├── integration/
│   └── live/                     # gated by env flag
├── scripts/                      # existing (build_affinity, etc.)
├── docker-compose.yml            # NEW
├── Dockerfile                    # NEW
├── pyproject.toml                # NEW
├── .env.example                  # NEW
└── README.md
```
