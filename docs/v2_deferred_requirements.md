# v2 Deferred Requirements

**Status:** Locked v0.1 (2026-05-26). Single source of truth for everything that v0.1 explicitly DEFERS to v2. Each entry includes: what's deferred + why deferred for v0.1 + cost estimate to add in v2 + dependent v0.1 design choices that hardcode the v0.1 behaviour.

**Purpose:** when v2 work begins, this doc is the to-do list. Nothing is "TBD" in the v0.1 codebase — everything is either built or explicitly deferred here.

---

## Categories

1. [Auth + multi-tenancy](#1-auth--multi-tenancy)
2. [API protocol features](#2-api-protocol-features)
3. [Storage + uploads](#3-storage--uploads)
4. [Concurrency + scale](#4-concurrency--scale)
5. [Agent + pack pipeline features](#5-agent--pack-pipeline-features)
6. [Frontend readiness](#6-frontend-readiness)
7. [Vendor integrations](#7-vendor-integrations)
8. [Data layer features](#8-data-layer-features)
9. [Observability + reporting](#9-observability--reporting)
10. [Deployment + ops](#10-deployment--ops)
11. [Tracked from data_lineage gap analysis](#11-from-data_lineage-gap-analysis)

---

## 1. Auth + multi-tenancy

### V2-AUTH-01 — Authentication mechanism
- **v0.1 behaviour:** None. Single trusted operator on 127.0.0.1.
- **v2 work:** Pick auth provider (Clerk / Supabase / custom JWT / passwordless magic links — TBD ADR); integrate; ship login UI.
- **v0.1 hardcoding:** `current_agency_id()` + `current_agent_id()` deps read from DB singleton. FastAPI binds to 127.0.0.1 by default. `agency_profile.agents[]` has `maxItems: 1`.
- **v2 cost:** ~1-3 weeks depending on provider choice.
- **Spec:** `docs/auth_and_authorization.md` § "v2 — Multi-tenant SaaS (deferred design)".

### V2-AUTH-02 — Multi-agent permissions (RBAC)
- **v0.1 behaviour:** Single agent does everything. `maxItems: 1` on `agency_profile.agents[]`.
- **v2 work:** Roles: `owner` / `operator` / `viewer` / `external_legal_reviewer`. `agency_agents.role` column. `@requires(roles=["owner", "operator"])` decorators.
- **v0.1 hardcoding:** Singleton agent.
- **v2 cost:** ~1 week.

### V2-AUTH-03 — Cross-agency isolation (3-layer defence)
- **v0.1 behaviour:** Single agency; isolation is N/A but repository-layer `agency_id` filter is in place from day 1.
- **v2 work:** Add middleware layer (URL agency_id matches JWT claim); add Postgres RLS policies on every domain table.
- **v0.1 hardcoding:** Repository layer always filters by `current_agency_id` (works for both v0.1 singleton + v2 JWT-derived).
- **v2 cost:** ~3-5 days incl. RLS policy authoring + tests.

### V2-AUTH-04 — CSRF protection + session revocation + 2FA + rate limiting + audit log
- **v0.1 behaviour:** N/A (no sessions).
- **v2 work:** Per `docs/auth_and_authorization.md` § "Required v2 behaviours".
- **v2 cost:** ~1 week.

### V2-AUTH-05 — agency_id propagation source change
- **v0.1 behaviour:** Singleton from `app.state.agency_id` set at startup.
- **v2 work:** Read from JWT claim. Update `current_agency_id()` dep.
- **v0.1 hardcoding:** Dep abstraction means only ~10 lines of code change in v2.
- **v2 cost:** ~half day for the swap + cross-agency boundary tests.

---

## 2. API protocol features

### V2-API-01 — Optimistic concurrency via If-Match / ETag
- **v0.1 behaviour:** Last-write-wins on all writes. No version negotiation.
- **v2 work:** Middleware adds `ETag` header on responses for versioned resources; validates `If-Match` on writes; returns 409 `CONFLICT_OPTIMISTIC_LOCK` on mismatch.
- **v0.1 hardcoding:** Pack schemas already carry `version` field (free, future-proof). Repository layer has no optimistic-lock logic.
- **v2 cost:** ~1 day for middleware + tests + frontend retry-on-409 handler.
- **Versioned resources at v2:** All pack types + `deal` + `talent` + `agency_profile` + `brand_candidate` + `brand_contact` + `brand_deal`.
- **Why deferred:** Zero contention at v0.1 single-operator scale.

### V2-API-02 — Cursor-based pagination
- **v0.1 behaviour:** Offset-based pagination on all list endpoints. `?page=1&page_size=50` with `meta.pagination: {page, page_size, total_count, total_pages}`.
- **v2 work:** Switch list endpoints to cursor (`?limit=50&cursor=<opaque>`); response gains `meta.pagination.next_cursor + has_more`.
- **v0.1 hardcoding:** Offset queries throughout repositories. ~12 list endpoints affected.
- **v2 cost:** ~2 days when dataset crosses ~10k rows per endpoint.
- **Why deferred:** v0.1 datasets are tiny (1 talent / ~30 candidates / ~5 deals); offset is fine.

### V2-API-03 — Idempotency-Key required on ALL writes
- **v0.1 behaviour:** Required only on `POST /resource` creates + `POST */:action` action endpoints. Optional on `PATCH` + `DELETE` (which are naturally idempotent on full-replace + soft-delete).
- **v2 work:** Tighten to required on every write endpoint regardless of method.
- **v0.1 hardcoding:** `REQUIRE_IDEMPOTENCY_KEY_ON_WRITES` env var; per-route enforcement decorator.
- **v2 cost:** ~1 day; mostly catching missing-key cases via tests.
- **Why deferred:** Reduced defensive overhead for v0.1 single-operator; PATCH/DELETE rarely double-fire.

### V2-API-04 — CORS for cross-origin frontend
- **v0.1 behaviour:** Disabled (no separate frontend origin; stub frontend deferred).
- **v2 work:** `CORSMiddleware` with allowed origins; credentials true; expose `ETag` + `X-Request-Id` + `X-LLM-Cost-USD`; preflight cache.
- **v2 cost:** ~half day.

### V2-API-05 — Rate limiting per-agency
- **v0.1 behaviour:** Per-vendor rate limits only (Anthropic / Meta / etc.). No per-agency caps.
- **v2 work:** Redis-backed counters per `(agency_id, endpoint_group)`. Defaults: 100 reads/sec, 10 writes/sec, 5 pack-generations/min.
- **v2 cost:** ~1 day.

---

## 3. Storage + uploads

### V2-STORAGE-01 — Presigned PUT uploads to S3
- **v0.1 behaviour:** Multipart upload through FastAPI. `POST /api/v1/uploads` accepts `multipart/form-data`; FastAPI streams to MinIO; returns `{attachment_id, s3_key, mime_type, size_bytes}`. Single-step protocol.
- **v2 work:** Two-step protocol: `POST /api/v1/uploads/presign` → presigned PUT URL → frontend uploads directly to S3 → `POST /api/v1/uploads/{id}/finalize`.
- **v0.1 hardcoding:** No `upload_id` returned until file received; no "in-flight upload" state.
- **v2 cost:** ~1-2 days when production traffic + larger files (>50MB videos) justify it.
- **Why deferred:** Local MinIO + v0.1 file sizes (briefs, contracts ≤ 10MB) handle multipart fine.

### V2-STORAGE-02 — S3 lifecycle policies + retention
- **v0.1 behaviour:** No lifecycle rules. Everything stays forever.
- **v2 work:** Lifecycle rules per prefix:
  - `tasks/*` — delete after 30d
  - `agencies/{id}/contract_template_starters/` — versioned indefinitely
  - `deals/*/context_uploads/` — keep for deal lifetime + 7y (legal retention)
- **v2 cost:** ~half day; mostly policy authoring.

### V2-STORAGE-03 — File antivirus scanning
- **v0.1 behaviour:** None. Trusted operator uploads only.
- **v2 work:** ClamAV (or similar) inline scanning on upload finalize.
- **v2 cost:** ~1 day.

### V2-STORAGE-04 — pgvector for semantic memo retrieval
- **v0.1 behaviour:** Tag-filter SQL retrieval only.
- **v2 work:** Add pgvector extension; embed `memo.content_markdown` at write-time via Anthropic embedding model; retrieval = tag filter + cosine similarity rank within filtered set.
- **v0.1 hardcoding:** No embedding column; `read_memos` is pure SQL.
- **v2 cost:** ~3-5 days incl. embedding pipeline + retrieval blending + tests.
- **Why deferred:** Tag filter is sufficient at v0.1 memo volume; vector adds operational complexity.

### V2-STORAGE-05 — Memo content offload to S3
- **v0.1 behaviour:** Memo `content_markdown` inline ≤ 32kB (schema-enforced via `maxLength`). Writes exceeding rejected with `VALIDATION_ERROR`.
- **v2 work:** When >32kB, write to S3 + set `content_markdown_s3_key`; `read_memos` lazy-loads on access.
- **v2 cost:** ~1 day.

---

## 4. Concurrency + scale

### V2-SCALE-01 — Celery queue split into 4
- **v0.1 behaviour:** 2 queues — `default` (CRUD + webhooks + cron + rendering + vendor APIs) + `llm_heavy` (pack generation).
- **v2 work:** Split into 4 — `default` / `llm_heavy` / `vendor_apis` (rate-limited) / `rendering` (CPU/IO mixed).
- **v0.1 hardcoding:** Two Celery worker processes; vendor API rate limits enforced at vendor-wrapper level (not queue-level).
- **v2 cost:** ~half day to split queues + reconfigure Celery Beat routing.
- **Why deferred:** v0.1 throughput trivial; 4-process ops overhead unnecessary.

### V2-SCALE-02 — Multi-process FastAPI workers
- **v0.1 behaviour:** Single uvicorn process (`NATIV2_API_WORKERS=1`).
- **v2 work:** Production deployment uses gunicorn + uvicorn workers (4+).
- **v2 cost:** ~half day; mostly process-coordination of in-memory state (singleton `app.state.agency_id` becomes per-request lookup).

### V2-SCALE-03 — Postgres read replicas
- **v0.1 behaviour:** Single Postgres instance.
- **v2 work:** Read replicas for heavy reports (LLM cost dashboards, perf reports listing).
- **v2 cost:** ~2 days infrastructure + repository read-routing.

### V2-SCALE-04 — Per-agency LLM budget caps
- **v0.1 behaviour:** Global daily soft cap + global daily hard kill (`LLM_BUDGET_DAILY_USD` + `LLM_BUDGET_HARD_KILL_DAILY_USD`).
- **v2 work:** Per-agency caps configured in `agency_profile.llm_budget_*`; track per-agency cumulative cost; surface DegradedModeError to specific agency when cap hit.
- **v2 cost:** ~1 day.

---

## 5. Agent + pack pipeline features

### V2-PACK-01 — Phase 4.5 prep pack slide rendering (HTML / PDF / PPTX)
- **v0.1 behaviour:** Prep pack ships as markdown deliverables only (briefing_notes.md + agenda.md + speaker_notes.md). Slide CONTENT is still generated and stored in `discovery_prep_pack.slides[]` (live_body / leave_behind_extension / speaker_notes per slide as markdown). No rendered visual artefacts.
- **v2 work:** Renderer subagent renders slides to HTML (live presenter view) + PDF (leave-behind) + PPTX (editable export). Agency branding applied. Playwright headless Chromium for PDF.
- **v0.1 hardcoding:** `discovery_prep_pack.export_artifacts[]` is populated with markdown-only artefacts in v0.1; rendered formats added in v2 without schema change.
- **v2 cost:** ~3-5 days for slide rendering pipeline (Jinja2 template + Playwright + branding application + tests).
- **Why deferred:** Prep pack is INTERNAL (agent's pre-call prep, not shown to brand). Markdown deliverables are sufficient for in-call agent reference. Slide rendering investment first pays off in M12 (proposal pack — brand-facing).

### V2-PACK-02 — Sibling commission invoice auto-generation
- **v0.1 behaviour:** When `commission_model = talent_invoices_brand_agency_invoices_talent`, agent manually creates the agency→talent commission invoice. UI nudge.
- **v2 work:** Auto-generate sibling invoice on the brand-facing invoice's `payment_received_at` event. Offset sequence per `invoice_pack_id`.
- **v2 cost:** ~2 days.
- **Tracked in:** `docs/data_lineage.md` GAP-09.

### V2-PACK-03 — Closed-loop `pitch_angles.json` authored_strength_score tuning
- **v0.1 behaviour:** `analyze_outreach.py` captures outcomes but does NOT update `authored_strength_score`. Manual angle tuning.
- **v2 work:** Auto-update strength scores from outcomeClassification statistics. Monthly cron writes back; agent confirms.
- **v2 cost:** ~2 days.
- **Tracked in:** `docs/data_lineage.md` GAP-04.

### V2-PACK-04 — Industry KPI benchmarks
- **v0.1 behaviour:** Performance report's `vs_industry` benchmark gracefully omitted (data file absent).
- **v2 work:** Ship `data/industry_kpi_benchmarks.json` + schema. Seed activewear, CPG, beauty, healthtech, fashion. Refresh quarterly.
- **v2 cost:** ~1 week (mostly data curation).
- **Tracked in:** `docs/data_lineage.md` GAP-03.

### V2-PACK-05 — LLM-eval cassette scenarios increase from 3 → 5+ per pack
- **v0.1 behaviour:** 3 cassette scenarios per pack type (15 total across 5 pack types). Nightly real-LLM run samples wider 10-scenario set.
- **v2 work:** Expand cassette library to 5+ per pack as product matures + edge cases discovered in production.
- **v2 cost:** Ongoing; no specific milestone.

### V2-PACK-06 — Pack regeneration cancellation mid-flight
- **v0.1 behaviour:** `POST /api/v1/tasks/{task_id}:cancel` endpoint specced but not implemented (Celery task soft-revocation tricky).
- **v2 work:** Implement cancellation via Celery revoke + cleanup partial work.
- **v2 cost:** ~2 days.

### V2-PACK-07 — Per-pack regeneration server-side debouncing
- **v0.1 behaviour:** Agent can hit "regenerate" multiple times rapidly (handled by Idempotency-Key on `:generate` action).
- **v2 work:** Soft debounce: reject regen within 10s of prior unless `--force`. Surfaces "wait for current run" UX.
- **v2 cost:** ~half day.

---

## 6. Frontend readiness

### V2-FRONT-01 — Stub frontend (Vue 3 + Vite + Playwright headless smoke)
- **v0.1 behaviour:** No stub frontend. API readiness validated via OpenAPI contract tests (schemathesis property-based) + OpenAPI review checklist used during PR reviews.
- **v2 work:** The PRODUCTION frontend (whatever stack chosen) supersedes the stub frontend concept entirely.
- **v0.1 hardcoding:** No node_modules in repo. No Vite config. No Playwright dependency.
- **v2 cost:** N/A — production frontend work doesn't depend on the stub.
- **Why deferred:** Stub frontend was a smoke harness; OpenAPI contract tests + review process catch the same issues at lower cost.

### V2-FRONT-02 — Server-Sent Events (SSE) for pack-generation progress
- **v0.1 behaviour:** Task-id polling. Frontend polls `GET /api/v1/tasks/{task_id}` every 2-5s.
- **v2 work:** Add SSE endpoint `GET /api/v1/tasks/{task_id}/stream`. Server pushes per-stage events (`stage_completed: researcher`, `stage_started: writer`, etc.).
- **v2 cost:** ~1-2 days.
- **Why deferred:** Polling is simpler + works through any proxy. SSE only adds value when frontend wants real-time progress UI.

### V2-FRONT-03 — Auto-generated TypeScript client (committed to frontend repo)
- **v0.1 behaviour:** Documented workflow: `npx openapi-typescript http://localhost:8000/openapi.json` on demand.
- **v2 work:** CI auto-generates + opens PR to frontend repo on backend release.
- **v2 cost:** ~half day in v2 when frontend ships.

---

## 7. Vendor integrations

### V2-VENDOR-01 — Stripe v2 invoice + payment automation
- **v0.1 behaviour:** Invoice rendered as PDF + sent manually via email. Payment received manually marked. No Stripe.
- **v2 work:** Integrate Stripe Invoicing API; auto-send invoice; webhook receiver populates `invoice_pack.payment_state.payment_received_at` on payment.
- **v0.1 hardcoding:** Schema already has `payment_received_at` + `payment_state` for v0.1 manual + v2 auto.
- **v2 cost:** ~1 week.
- **Webhook spec:** `POST /webhooks/stripe/invoice_paid` (already documented).

### V2-VENDOR-02 — DocuSign / HelloSign for contract e-signature
- **v0.1 behaviour:** Contract PDF generated; agent emails to brand + receives signed copy back as upload.
- **v2 work:** Integrate DocuSign API. Auto-send for signature; webhook receiver populates `signed_at` + signed PDF.
- **v2 cost:** ~1 week.

### V2-VENDOR-03 — Phyllo for non-Meta/TikTok platform detection (YouTube / LinkedIn / X / podcast / Substack)
- **v0.1 behaviour:** Meta Graph + TikTok Display APIs only (covers IG + TikTok). YouTube / others = agent manual URL entry.
- **v2 work:** Integrate Phyllo (or equivalent) for unified multi-platform detection.
- **v2 cost:** ~1-2 weeks.

### V2-VENDOR-04 — Modash / HypeAuditor bulk brand DB import
- **v0.1 behaviour:** Manual brand_industry_map curation + discovery's Search 15/16 growth loop.
- **v2 work:** Bulk import from creator-economy databases.
- **v2 cost:** ~1 week.

### V2-VENDOR-05 — Tribe Dynamics EMV data
- **v0.1 behaviour:** EMV not tracked; kpiMetric.source = `third_party` reserved for it.
- **v2 work:** Subscribe + integrate; backfill historical brand_deals with EMV figures.
- **v2 cost:** ~1 week + ongoing subscription.

### V2-VENDOR-06 — Deferred vendor evaluations
Per `docs/vendor_roadmap.md`:
- ScrapeCreators (Search 16 visual platforms)
- Owler (competitor maintenance)
- Exploding Topics (pre-trend detection)
- Product Hunt API (day-of launches)
- SimilarWeb (audience-overlap competitors)
- Crunchbase (structured funding data)

### V2-VENDOR-07 — Similar-talent sponsor-history automation (Modash / HypeAuditor)
- **v0.1 behaviour:** Agency operator manually enters similar-talent peers + their past sponsored brands into `talent.data.similar_talent[]` after looking at each peer's Instagram / TikTok profile. ~10 min per peer. Phase 1's `similar_talent` walk seeds + Phase 3 S2 (`similar_talent_worked_with`) and S4 (`competitor_of_similar_talent`) consume the manual data unchanged. Researched 2026-06-01: Exa web search cannot reliably extract sponsor disclosures from Instagram/TikTok posts (login walls + non-indexable captions); the M7.7+ live test against James Breakwell returned only LLM-pattern-matched category guesses with no evidence-based partnerships, confirming the manual path for v0.1.
- **v2 work:** Integrate Modash OR HypeAuditor API. Per peer handle, pull structured `[{brand_name, post_url, posted_at, disclosure_tag (#ad/#sponsored/#gifted), engagement_rate}]` history. Map brand_name → industry_id via taxonomy lookup + LLM fallback. Background Celery job refreshes peer sponsor history weekly; new brands flow into the agency inventory automatically tagged with `source="peer_sponsor_history"`. Removes the manual entry step entirely for any peer once added.
- **v2 cost:** ~3-5 days build + ongoing vendor subscription (Modash starts ~$300-1500/mo per workspace depending on creator volume; HypeAuditor similar). Adds ~$0.50-2.00 per peer per refresh in API calls.

---

## 8. Data layer features

### V2-DATA-01 — `brand_candidates.candidates[].pitch_history[]` legacy deprecation
- **v0.1 behaviour:** Field retained for backward compatibility; canonical source is `pitch_enrollment`.
- **v2 work:** Migration drops the legacy field. UI reads switch to `pitch_enrollment` queries via `brand_id`.
- **v2 cost:** ~1 day.
- **Tracked in:** `docs/data_lineage.md` GAP-05.

### V2-DATA-02 — Formal schemas for `industries.json` + `niches.json` + `pitch_templates.json`
- **v0.1 behaviour:** Data files exist + are stable; no formal JSON Schema validation.
- **v2 work:** Add `schemas/industries.schema.json` (proposed — not yet shipped) + `schemas/niches.schema.json` (proposed — not yet shipped).
- **v2 cost:** ~half day each.
- **Tracked in:** `docs/data_lineage.md` GAP-14.

### V2-DATA-03 — `pitch_templates.json` authoring workflow
- **v0.1 behaviour:** Templates edited directly in JSON file.
- **v2 work:** Agency-facing template editor UI + version control.
- **v2 cost:** ~3-5 days incl. UI.
- **Tracked in:** `docs/data_lineage.md` GAP-11.

### V2-DATA-04 — `talent.id` agency-scoped uniqueness (composite constraint)
- **v0.1 behaviour:** Globally unique slugs.
- **v2 work:** Composite UNIQUE `(agency_id, talent.id)`; allows two agencies to both have `riley-carter`.
- **v0.1 hardcoding:** Single-column UNIQUE on `talent.id`.
- **v2 cost:** ~half day migration + tests.
- **Tracked in:** `docs/data_lineage.md` GAP-N3.

### V2-DATA-05 — Server-side audience demographics snapshot store
- **v0.1 behaviour:** `brand_deal.audience_demographics_at_campaign_time` populated at auto-archive (best-effort; may have drifted from campaign-end demos).
- **v2 work:** Snapshot demographics during Phase 4.9 KPI capture cron (when first posted_at occurs); store dedicated table; auto-archive copies from snapshot table.
- **v2 cost:** ~2 days.
- **Tracked in:** `docs/data_lineage.md` GAP-13.

### V2-DATA-06 — `kpiMetric` $def fully extracted (no $defs duplication)
- **v0.1 behaviour:** Shared via `$ref: _shared/kpi_metric.schema.json`; both consumer schemas use a `$defs.kpiMetric` wrapper preserving intra-schema references.
- **v2 work:** Remove the wrapper; consumers use the cross-file `$ref` directly throughout.
- **v2 cost:** ~half day; potentially blocked by Pydantic codegen tool support.

### V2-DATA-07 — Soft-delete `deleted_by_agent_id` enforcement
- **v0.1 behaviour:** Column exists in schema but defaults to singleton agent in v0.1; not enforced as a required write.
- **v2 work:** Enforce population from JWT-derived agent_id; reject writes without it.
- **v2 cost:** ~half day.

### V2-DATA-08 — Per-agency template starter library
- **v0.1 behaviour:** Single `data/contract_template_starters/` directory; shared if multiple agencies (which there aren't in v0.1).
- **v2 work:** Per-agency starter library: `data/contract_template_starters/{agency_id}/`.
- **v2 cost:** ~1 day.

---

## 9. Observability + reporting

### V2-OBS-01 — Sentry production tier + alerting
- **v0.1 behaviour:** Sentry optional in dev; recommended in prod (env var only).
- **v2 work:** Sentry production project + alert routing per error severity; on-call rotation if applicable.
- **v2 cost:** ~half day setup.

### V2-OBS-02 — Langfuse cloud (vs self-hosted)
- **v0.1 behaviour:** Self-hosted via Docker Compose for local dev.
- **v2 work:** Migrate to Langfuse Cloud for prod (or stay self-hosted at scale).
- **v2 cost:** ~half day.

### V2-OBS-03 — LLM cost dashboards
- **v0.1 behaviour:** `nativ test report` CLI + nightly cost report. No interactive dashboard.
- **v2 work:** Grafana / Metabase dashboards on Postgres + Langfuse data. Per-agency / per-talent / per-deal / per-pack-type cost rollups.
- **v2 cost:** ~3-5 days.

### V2-OBS-04 — Audit log table
- **v0.1 behaviour:** Stage history per deal + pack version history per pack. No generic cross-resource audit log.
- **v2 work:** Dedicated `audit_log` table capturing every write across the system (agency_id, agent_id, resource_type, resource_id, action, before, after, timestamp). 90-day retention.
- **v2 cost:** ~2 days.

### V2-OBS-05 — Performance dashboards
- **v0.1 behaviour:** Sentry perf traces only.
- **v2 work:** APM dashboards; slow query log; pack-generation time distributions per pack type.
- **v2 cost:** ~3 days.

---

## 10. Deployment + ops

### V2-OPS-01 — Production hosting decision
- **v0.1 behaviour:** Local Docker Compose only.
- **v2 work:** Pick hosting (Railway / Fly.io / AWS / GCP — TBD ADR); CI/CD pipeline; secrets management (Doppler / AWS SM / etc.); zero-downtime deploys.
- **v2 cost:** ~1-2 weeks depending on stack.

### V2-OPS-02 — Backup + DR
- **v0.1 behaviour:** No formal backup strategy; data is local + ephemeral.
- **v2 work:** Postgres daily snapshots + WAL archiving; S3 versioning + cross-region replication; documented RPO ≤ 1h + RTO ≤ 4h.
- **v2 cost:** ~3-5 days.

### V2-OPS-03 — GDPR right-to-erasure tooling
- **v0.1 behaviour:** Soft-delete only; no hard-purge tool.
- **v2 work:** `nativ admin purge --agency-id X --talent-id Y` CLI that hard-deletes after a 30-day grace period; cascades through all related records; produces a deletion certificate.
- **v2 cost:** ~3-5 days.

### V2-OPS-04 — Encrypted backup keys + key rotation
- **v0.1 behaviour:** `DB_MASTER_KEY` in `.env`; manual rotation discipline.
- **v2 work:** Key management via cloud KMS (AWS KMS / GCP KMS); auto-rotation; envelope encryption.
- **v2 cost:** ~3-5 days.

### V2-OPS-05 — Multi-environment promotion (dev → staging → prod)
- **v0.1 behaviour:** Local-only. `NATIV2_ENVIRONMENT` enum supports `development | test | production` but only `development` is used.
- **v2 work:** CI/CD promotion pipeline; per-env config; staging fixture.
- **v2 cost:** Captured in V2-OPS-01.

---

## 11. From data_lineage gap analysis

These are tracked in `docs/data_lineage.md` § 4 and aliased here for visibility:

| Lineage Gap ID | v2 ID | Description |
|---|---|---|
| GAP-03 | V2-PACK-04 | Industry KPI benchmarks |
| GAP-04 | V2-PACK-03 | pitch_angles closed-loop tuning |
| GAP-05 | V2-DATA-01 | brand_candidate.pitch_history deprecation |
| GAP-09 | V2-PACK-02 | Sibling commission invoice auto-gen |
| GAP-11 | V2-DATA-03 | pitch_template authoring workflow |
| GAP-14 | V2-DATA-02 | Formal schemas for static data files |

---

## Capability matrix: v0.1 vs v2

For quick reference — which capabilities work in which version.

| Capability | v0.1 | v2 |
|---|---|---|
| Single agency, single agent | ✅ | ✅ |
| Multi-agency multi-tenant | ❌ | ✅ |
| Multi-agent within agency | ❌ | ✅ |
| Auth + login | ❌ | ✅ |
| Cross-tenant isolation | N/A | ✅ |
| Last-write-wins | ✅ | ⏭ replaced by optimistic |
| Optimistic concurrency (ETag) | ❌ | ✅ |
| Cursor pagination | ❌ | ✅ |
| Offset pagination | ✅ | ⏭ deprecated |
| Multipart uploads | ✅ | ⏭ replaced by presigned PUT |
| Presigned PUT uploads | ❌ | ✅ |
| Idempotency-Key on creates + actions | ✅ | ✅ |
| Idempotency-Key on PATCH/DELETE | optional | required |
| Task-id polling | ✅ | ✅ |
| SSE pack-progress streaming | ❌ | ✅ (V2-FRONT-02) |
| Prep pack rendered slides | ❌ | ✅ (V2-PACK-01) |
| Prep pack markdown deliverables | ✅ | ✅ |
| Proposal pack rendered slides | ✅ | ✅ |
| Contract pack rendered MD+DOCX+PDF | ✅ | ✅ |
| Stub frontend smoke | ❌ | N/A (real frontend ships) |
| OpenAPI contract tests (schemathesis) | ✅ | ✅ |
| 2 Celery queues | ✅ | ⏭ |
| 4 Celery queues | ❌ | ✅ (V2-SCALE-01) |
| Per-vendor rate limits | ✅ | ✅ |
| Per-agency rate limits | ❌ | ✅ (V2-API-05) |
| Tag-filter memo retrieval | ✅ | ✅ |
| Vector memo retrieval | ❌ | ✅ (V2-STORAGE-04) |
| Anthropic + Smartlead + Exa + Meta Graph + TikTok | ✅ | ✅ |
| Stripe invoice automation | ❌ | ✅ (V2-VENDOR-01) |
| DocuSign contract automation | ❌ | ✅ (V2-VENDOR-02) |
| Phyllo platform detection | ❌ | ✅ (V2-VENDOR-03) |
| Sibling commission invoice | manual | auto (V2-PACK-02) |
| Industry KPI benchmarks | gracefully omitted | populated (V2-PACK-04) |
| Closed-loop pitch_angles tuning | manual | auto (V2-PACK-03) |
| Audit log table | ❌ (stage_history only) | ✅ (V2-OBS-04) |
| Production hosting | local-only | TBD (V2-OPS-01) |
| Backup + DR | ❌ | ✅ (V2-OPS-02) |
| GDPR right-to-erasure | ❌ | ✅ (V2-OPS-03) |
| 5+ cassette scenarios per pack | 3 | 5+ (V2-PACK-05) |
| Production frontend | ❌ | ✅ |

---

## Adoption checklist (when v2 work begins)

When you're ready to start v2:

1. Re-read this doc end-to-end.
2. Open a v2 architecture review ADR (decisions on auth provider + hosting + frontend stack).
3. Triage: which v2 items are MUST for SaaS launch vs nice-to-have for v2.1+.
4. Create v2 milestones in a new `docs/v2_project_plan.md` (proposed — not yet shipped; parallel to current `docs/project_plan.md`).
5. For each v2 item, the entry above contains the cost estimate + the v0.1 hardcoded behaviour to replace.

Roughly: full v2 = ~3-6 months of work depending on hosting + auth choices.
