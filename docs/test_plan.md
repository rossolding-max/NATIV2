# Test Plan — Backend

**Status:** Locked v0.1 (2026-05-26). Comprehensive test architecture for the NATIV2 backend. Pairs with `docs/architecture.md` (what we build) + `docs/project_plan.md` (build sequence) + `docs/data_lineage.md` (wiring map). Backend only — frontend test plan deferred.

**Two test phases:**
1. **Automated test suite** — runs in CI on every PR + nightly. Synthetic fixture only (Acme Talent Agency + Riley Carter). Hybrid LLM eval (cassettes by default + real LLM nightly).
2. **Hands-on CLI test session** — real agency + real talent. Fixture lives locally only (`~/.nativ/test_fixtures/`); never committed. Run via `nativ test ...` CLI tool against a running local stack.

---

## 1. Strategy

### 1.1 Coverage target — 100% everywhere

100% is the target. The metric varies by module type, because line coverage doesn't capture every kind of correctness:

| Module type | Metric | Why |
|---|---|---|
| Imperative code (services, repositories, utils, API handlers, webhook receivers, validation, encryption) | **100% line coverage** | Standard. Every branch + error path is reachable from some test. |
| State machines (`deal`, `pitch_enrollment`, `posted_detection`, `payment_state`) | **100% transition coverage** (valid + invalid) | Combinatorial; a 90% line coverage on a state machine can still miss an illegal transition that crashes in production. |
| Schemas (Pydantic ↔ SQLAlchemy ↔ JSON Schema) | **100% round-trip coverage** per schema | Every field has a fixture that round-trips through all three representations cleanly. |
| API endpoints | **100% contract coverage** | Every endpoint: success path + each documented error path + authz boundaries + OpenAPI schema validation. |
| Agent code (researcher / writer / extractor / renderer coordination) | **100% LLM eval pass rate** against golden test sets | Line coverage on an agent loop tells you nothing about whether it produces good packs. Eval test sets per pack type measure actual quality. |
| Webhook receivers | **100% signature validation coverage** + idempotency | Untrusted external input; signature bypass is a security bug. |
| Celery tasks | **100% scenario coverage** (success + retry + timeout + failure-handling) | Async failures eat themselves silently otherwise. |

### 1.2 Test pyramid + categories

| Layer | What | Tooling | Speed | Cost | Coverage |
|---|---|---|---|---|---|
| **Unit** | Per-function, per-class. Mocked dependencies. | pytest + pytest-asyncio + factory_boy | <1ms each | $0 | Line coverage 100% on imperative code |
| **Integration** | Multi-module, real Postgres + Redis + S3 (MinIO). Mocked external vendors via respx. | pytest + testcontainers (or docker-compose) + respx | 10-100ms | $0 | All cross-module flows + skip-handling paths |
| **API contract** | Every endpoint: shape + status codes + authz. OpenAPI-spec-driven. | pytest + schemathesis | 50-200ms | $0 | 100% endpoint coverage |
| **Webhook receiver** | Signature validation + idempotency + payload parsing. | pytest + recorded webhook payloads | 10-50ms | $0 | 100% webhook coverage |
| **State machine** | Every valid + invalid transition for each state machine. | pytest + parameterised tests | <5ms | $0 | 100% transition coverage |
| **LLM eval (cassette)** | Pack-level agent outputs against recorded LLM responses. | pytest + vcrpy + golden assertions | 100ms-2s | $0 post-record | Default for PRs + on-merge |
| **LLM eval (real)** | Same evals against live Anthropic API. Nightly only. | pytest + live API key + budget gate | 30s-3min per pack | $5-20/night | Catches prompt-engineering regressions |
| **End-to-end** | Full pipelines through FastAPI: agency setup → talent onboarding → discovery → outreach → deal → pack → invoice → archive. | pytest + httpx client + spun-up FastAPI | 2-10s per scenario | $0 (cassettes) | Critical-path scenarios |
| **OpenAPI smoke** | Stub frontend (Vue 3 + Vite) wires up agency setup wizard against `/openapi.json`. | Playwright headless | 10-30s | $0 | Proves the API surface is UI-shaped |
| **Performance** | Load test: 50 concurrent deals across 10 talents. Profile slow queries + Celery throughput. | Locust + pytest-benchmark | 5-30min | $0 | M17 production hardening |
| **Security** | Secret leakage scan + SQL injection + authz boundary tests + dependency vuln scan. | trufflehog + bandit + safety + pytest authz | 1-5min | $0 | M17 + every release |

### 1.3 Fixture strategy

**Synthetic (committed):** `tests/fixtures/synthetic/` — Acme Talent Agency + Riley Carter (fitness influencer). Hand-curated to exercise every code path. CI runs exclusively against this. See § 6 for full fixture spec.

**Real (gitignored):** `~/.nativ/test_fixtures/` — outside the repo entirely. Real agency + real talent that the operator runs locally for manual end-to-end verification. Test suite detects presence: if found, gain access to additional `@requires_real_fixture` test markers; if absent, tests skip cleanly with `SKIPPED [no real fixture]`.

**Database state:** transaction-wrapped per test (every test rolls back at teardown). Shared session-scoped fixture DB via testcontainers Postgres. Migrations applied once at session start.

### 1.4 CI gating + nightly

| Gate | When | Suites run | Budget |
|---|---|---|---|
| Pre-commit (developer) | `git commit` | Lint (ruff) + typecheck (pyright) + format + fast unit tests | <30s |
| Pre-push (developer) | `git push` | Above + full unit + integration + schema round-trip | <3min |
| CI on PR | `pull_request` | Above + API contract + webhook + state machine + LLM eval (cassette) + end-to-end (cassette) | <8min |
| CI on merge to main | `push to main` | Above + OpenAPI stub frontend smoke | <12min |
| Nightly | 02:00 UTC daily | All of the above + LLM eval (real Anthropic) + performance smoke | <30min; ~$10-25 LLM cost |
| Pre-release | Manual tag | All of the above + security audit + load test | <2hr |

**Fail-fast discipline:** failed pre-commit blocks the commit. Failed CI gate blocks merge. Nightly failures notify Sentry + a dedicated alert channel.

### 1.5 Test ordering (hybrid approach)

Tests aren't all authored upfront — they accrete alongside the build:

- **Foundation scaffolding upfront (M0-M2):** test infrastructure, fixtures, CI pipeline, base classes for unit / integration / LLM eval tests. No production tests yet.
- **Per-milestone tests (M3-M16):** as each milestone is built, its tests are authored in the same PR. No milestone is "done" without its tests passing.
- **End-to-end + LLM eval tests (M11 onwards):** the first AI pack milestone (M11) introduces LLM eval cassettes + the first multi-phase e2e scenario; each subsequent pack milestone adds to both.
- **Performance + security (M17):** the production-hardening milestone is where load + perf + security audit work happens.

---

## 2. Per-milestone test deliverables (M0-M17)

Maps every milestone in `docs/project_plan.md` to the tests it ships with.

### M0 — Repo foundation
**Tests authored:**
- `tests/conftest.py` — session-scoped fixtures: Postgres (testcontainers), Redis, MinIO, Anthropic mock
- `tests/factories/` — factory_boy factories for every schema (auto-generated stubs)
- CI workflow `.github/workflows/test.yml` with all 5 gate stages
- Smoke tests: FastAPI `/health` returns 200; Celery worker accepts + executes echo task; Postgres + Redis + MinIO reachable

**Acceptance:** `docker compose up && pytest tests/` passes with at least 5 trivial tests; CI workflow green on a no-op commit.

### M1 — Data layer
**Tests authored:**
- `tests/unit/schemas/test_pydantic_codegen_drift.py` — runs `datamodel-code-generator`; fails if generated diff exists
- `tests/integration/test_schema_roundtrip.py` — for each of 16 schemas: load JSON → Pydantic validate → SQLAlchemy save → SQLAlchemy load → Pydantic validate → JSON dump → JSON Schema validate
- `tests/integration/test_alembic_migrations.py` — every migration goes UP + DOWN cleanly; idempotency check
- `tests/integration/test_pgcrypto.py` — encrypted columns round-trip; wrong master key fails; tampered ciphertext fails
- `tests/integration/test_repositories.py` — CRUD per repository; multi-tenant agency_id filter enforcement

**Acceptance:** 290 brand_industry_map records import into Postgres + re-export with byte-identical JSON.

### M2 — Agent infrastructure
**Tests authored:**
- `tests/unit/agents/test_base_agent.py` — base class invocation; Langfuse trace capture; error propagation
- `tests/integration/agents/test_skill_subagents.py` — researcher / writer / extractor / renderer each invokable with minimal bundle
- `tests/integration/agents/test_tool_catalog.py` — every shared tool callable + returns correct shape:
  - `get_talent`, `get_deal`, `get_brand_record` (FK resolution)
  - `read_memos` with various filter combinations (talent_id only / brand_id only / industry_id only / topics + scope; tag-filter SQL correctness)
  - `write_memo` schema validation
  - `validate_schema`, `render_template`
- `tests/integration/agents/test_bundle_composer.py` — for each pack type, bundle composer produces expected fields per `docs/architecture.md` § 6 matrix
- `tests/llm_eval/test_smoke_pack_gen.py` — minimal cassette-recorded coordinator + skill invocation producing a 1-slide output

**Acceptance:** orchestrator can invoke 2 skill subagents in sequence + write + read memos; Langfuse trace shows full span tree.

### M3 — Vendor wrappers
**Tests authored:** for each vendor (Anthropic, Smartlead, Exa, Apollo, LinkedIn, Meta Graph, TikTok):
- `tests/integration/vendors/test_{vendor}.py` — happy path with respx-mocked responses
- `tests/integration/vendors/test_{vendor}_rate_limits.py` — exceeding budget surfaces correct error
- `tests/integration/vendors/test_{vendor}_retries.py` — exponential backoff on 5xx / 429
- `tests/live/vendors/test_{vendor}_live.py` — env-gated live smoke (`pytest -m live`); requires real API key

**Acceptance:** mock-mode passes all 7 vendor module test suites; `pytest -m live` passes with real keys (one-time verification).

### M4 — Phase 0 (Agency Setup)
**Tests authored:**
- `tests/unit/services/test_dns_validation.py` — SPF/DKIM/DMARC parsing + Smartlead-status mapping
- `tests/integration/api/test_agencies.py` — full 9-step setup via API; rejects incomplete setups; idempotent updates
- `tests/integration/services/test_invoice_template.py` — sequence counter atomic increment under concurrent calls
- `tests/integration/services/test_agency_warmup.py` — warmup webhook handler transitions state correctly
- `tests/contract/test_agencies_openapi.py` — OpenAPI shape per endpoint
- `tests/state_machine/test_agency_setup_state.py` — all 9 step transitions

**See also:** § 3.0 (per-app-phase Phase 0 tests).

### M5 — Phase 1 (Talent Onboarding)
**Tests authored:**
- `tests/unit/services/test_media_pack_extraction.py` — PDF + DOCX parsing; LLM extraction cassette
- `tests/integration/api/test_talents.py` — full 8-step onboarding; oAuth validation gate; commission_override capture
- `tests/integration/services/test_platform_oauth.py` — Meta / TikTok / YouTube oAuth flows; encrypted token storage; scope validation
- `tests/integration/services/test_contract_template_setup.py` — adoption + validation (every merge field defined, every {{#if}} has rule, dry-run compose passes)
- `tests/contract/test_talents_openapi.py`
- `tests/skip_handling/test_phase1_optional_steps.py` — onboarding completes with skipped optional steps; downstream features degrade gracefully

**See also:** § 3.1.

### M6 — Phase 1.5 (Brand Deals capture)
**Tests authored:**
- `tests/unit/services/test_kpi_validation.py` — honesty-floor enforcement (source + as_of required)
- `tests/integration/api/test_brand_deals.py` — 3 ingestion paths
- `tests/integration/services/test_brand_deal_computed_fields.py` — renewal_eligibility_date / CPM / CPE / CTR derivations
- `tests/contract/test_brand_deals_openapi.py`

### M7 — Phase 2 (Brand Discovery)
**Tests authored:**
- `tests/unit/services/test_discovery_searches.py` — each of 16 search modules with mocked inputs
- `tests/integration/services/test_qualification.py` — signal-score → tier assignment
- `tests/integration/services/test_policy_filter.py` — blocked_industries / active_exclusivities / values_red_lines
- `tests/integration/tasks/test_discovery_run.py` — full monthly cron simulation
- `tests/integration/services/test_brand_enrichment.py` — social_handles capture writeback (G1 fix verification)

### M8 — Phase 3a (Contact CRM)
**Tests authored:**
- `tests/unit/services/test_decision_role_classification.py` — LLM classification cassette
- `tests/integration/api/test_brand_contacts.py`
- `tests/integration/services/test_contact_enrichment.py` — Apollo + LinkedIn + Exa fallback chain
- `tests/integration/services/test_do_not_contact.py` — DNC enforcement across talents (shared roster)

### M9 — Phase 3b (Outreach)
**Tests authored:**
- `tests/unit/services/test_outreach_template_selection.py` — decision_role → template variant
- `tests/integration/services/test_outreach_generation.py` — per-step LLM generation cassette
- `tests/integration/webhooks/test_smartlead_email_event.py` — engagement events write to enrollment
- `tests/integration/webhooks/test_smartlead_reply.py` — reply classification + on `interested` creates deal with bidirectional FK setup (G3 fix verification)
- `tests/integration/tasks/test_enrollment_state_sync.py` — 5-min cron behaviour
- `tests/state_machine/test_pitch_enrollment_state.py` — all transitions
- `tests/integration/services/test_brand_candidate_status_sync.py` — verify GAP-06 sync discipline implementation

### M10 — Phase 4 (Deal Lifecycle skeleton)
**Tests authored:**
- `tests/unit/services/test_deal_state_machine.py` — every documented substage transition (31 substages × valid → invalid)
- `tests/integration/api/test_deals.py` — CRUD + transitions
- `tests/integration/services/test_deal_computed_fields.py` — delivery substage least-progressed-wins; performance_capture_window_* computation; all_invoices_paid_at trigger
- `tests/state_machine/test_deal_substage_transitions.py` — exhaustive

### M11 — Phase 4.5 (Discovery Prep Pack) ⭐
**Tests authored:**
- `tests/integration/agents/packs/test_discovery_prep_smoke.py` — bundle composes, agent invokes, output validates against schema
- `tests/llm_eval/discovery_prep/test_briefing_quality.py` — golden test set (5 scenarios; assertions on key fields present + sourced + word count)
- `tests/llm_eval/discovery_prep/test_slide_generation.py` — slides match expected types + position; live_body + leave_behind_extension present
- `tests/llm_eval/discovery_prep/test_speaker_notes.py` — speaker notes generated with correct cues
- `tests/integration/tasks/test_phase_4_5_auto_fire.py` — substage transition triggers pack gen
- `tests/integration/agents/test_nl_feedback_regen.py` — v1 → v2 with agent feedback; is_latest flips correctly
- `tests/e2e/test_p4_5_full_lifecycle.py` — onboarded talent + active deal → prep pack PDF + HTML + speaker notes generated; cost tracked

**LLM eval discipline:** record cassettes at first authorial run; re-record nightly via `pytest -m llm_eval_record`.

### M12 — Phase 4.6 (Proposal Pack)
**Tests authored:**
- `tests/integration/agents/packs/test_proposal_full_pipeline.py` — 5-stage pipeline (Stage A→E) with cassette LLM
- `tests/llm_eval/proposal/test_discovery_debrief_extraction.py` — 10 structured fields populated from brief upload
- `tests/integration/api/test_commercial_gate.py` — render BLOCKED until agent confirms commercial values (HARD GATE)
- `tests/integration/services/test_proposal_to_deal_writeback.py` — `deal.proposal.*` canonical values populated on confirm
- `tests/integration/services/test_proposal_negotiation_bidirectional_fk.py` — `deal.proposal.negotiation_log[].proposal_pack_version` ↔ pack version
- `tests/e2e/test_p4_6_full_lifecycle.py`

### M13 — Phase 4.7 (Contract Pack)
**Tests authored:**
- `tests/integration/agents/packs/test_contract_full_pipeline.py` — 7-stage pipeline
- `tests/llm_eval/contract/test_merge_field_extraction.py` — every {{merge_field}} resolved with provenance
- `tests/llm_eval/contract/test_conditional_clause_evaluation.py` — each clause include/exclude decision matches expected
- `tests/integration/api/test_legal_review_gate.py` — render BLOCKED until reviewer approves
- `tests/integration/services/test_disclosure_clause_wiring.py` — talent.disclosure_defaults.style flows into {{disclosure_style}} merge field (O5 fix verification)
- `tests/integration/services/test_amendment_bidirectional_fk.py` — amendment_log[].contract_pack_version ↔ pack (G5 fix verification)
- `tests/e2e/test_p4_7_full_lifecycle.py`

### M14 — Phase 4.8 (Invoice Pipeline)
**Tests authored:**
- `tests/unit/services/test_posted_detection_scoring.py` — scoring algorithm; brand_handles + campaign_hashtags consumed (G1 + G2 fix verification)
- `tests/integration/tasks/test_phase_4_8_detection_cron.py` — Meta + TikTok poll cycles; agent confirmation flow
- `tests/integration/services/test_payment_terms_llm_parse.py` — contract payment_terms → invoice_schedule[]
- `tests/integration/services/test_invoice_generation.py` — per-trigger invoice pack
- `tests/integration/services/test_invoice_numbering_concurrency.py` — atomic counter under N concurrent gens
- `tests/integration/services/test_commission_resolution.py` — FROM-party determination across all 4 commission models
- `tests/integration/services/test_all_invoices_paid_computation.py` — `deal.close.all_invoices_paid_at` computed correctly
- `tests/integration/tasks/test_invoice_overdue_reminders.py`

### M15 — Phase 4.9 (Performance Report)
**Tests authored:**
- `tests/integration/tasks/test_phase_4_9_kpi_capture_cron.py` — daily cron writes per-post snapshots
- `tests/integration/services/test_kpi_aggregation.py` — interim_kpi_snapshots → final kpis{} (sum vs weighted-avg correctness)
- `tests/integration/services/test_benchmark_comparisons.py` — vs_industry (graceful omission) / vs_talent_historical / vs_brand_stated_targets
- `tests/llm_eval/performance_report/test_narrative_quality.py` — executive_summary + what_worked + learnings with declared sources
- `tests/integration/services/test_final_kpis_auto_population.py` — agent send populates `deal.close.final_kpis` verbatim
- `tests/e2e/test_p4_9_full_lifecycle.py`

### M16 — Auto-archive loop closure
**Tests authored:**
- `tests/integration/tasks/test_auto_archive_trigger_check.py` — 3-gate condition logic
- `tests/integration/services/test_brand_deal_creation_from_deal.py` — kpis verbatim carry; bidirectional FKs set
- `tests/integration/services/test_deal_archive_idempotency.py` — re-firing archive is a no-op
- `tests/e2e/test_full_loop_closure.py` — outreach reply → prep → proposal → contract → delivery detection → invoice → performance report → auto-archive → brand_deal exists in talent's file

### M17 — Production hardening
**Tests authored:**
- `tests/performance/test_concurrent_deals.py` — Locust: 50 concurrent deals across 10 talents
- `tests/performance/test_slow_queries.py` — every endpoint p95 < 500ms (excluding LLM)
- `tests/security/test_secret_leakage.py` — trufflehog scan of repo
- `tests/security/test_dependency_vulns.py` — safety scan
- `tests/security/test_authz_boundaries.py` — agency A cannot read agency B's data
- `tests/security/test_webhook_signature_bypass.py` — invalid signatures rejected for all 4 webhook receivers
- `tests/security/test_sql_injection.py` — sqlmap-style injection attempts blocked

---

## 3. Per-app-phase test deliverables (P0 – P4.9 + A)

Where § 2 maps test deliverables to BUILD milestones, this section maps the COMPLETE test suite per RUNTIME phase. Each phase has 4 test layers.

### 3.0 — P0 (Agency Setup)

**Unit:**
- `tests/unit/services/test_branding_upload.py` — S3 path resolution + presigned URL signing
- `tests/unit/services/test_dns_validation.py` — SPF/DKIM/DMARC parsing
- `tests/unit/services/test_signature_template.py` — required tokens validation ({unsubscribe_link} / {agency_address} / {agent_name})
- `tests/unit/services/test_invoice_template_version.py` — version bump enforcement on field changes (GAP-07 fix)

**Integration:**
- All 9 setup steps end-to-end
- Smartlead warmup webhook → state transitions
- Invoice template starter + atomic sequence counter
- Multi-mailbox per agency (v0.2 ready) — currently 1 mailbox v0.1

**E2E:**
- Cold-start: empty Postgres → POST /agencies (9-step wizard) → GET /agencies/{id} returns full populated profile → assert all 9 step fields present + warmup complete

**LLM eval:** None — Phase 0 is pure CRUD.

### 3.1 — P1 (Talent Onboarding)

**Unit:**
- `tests/unit/services/test_questionnaire_adaptive.py` — adaptive question flow per declared niche / platform / billing entity
- `tests/unit/services/test_disclosure_defaults_country.py` — country code → disclosure_style mapping
- `tests/unit/services/test_contract_template_version.py` — version bump enforcement (GAP-08 fix)

**Integration:**
- Steps 1-8 sequential + idempotent re-runs
- oAuth flows: Meta + TikTok + YouTube each with success + denial + expired token paths
- Media pack extraction: PDF + DOCX + PNG happy paths + corrupted file rejection
- contract_template.dry_run_compose: every {{merge_field}} resolves; every {{#if}} evaluates; every {{narrative_*}} placeholder declared

**E2E:**
- Empty agency → talent created → all platforms connected with valid scopes → contract_template adopted → deal-readiness check passes

**LLM eval:**
- Media pack extraction quality: 5 sample media packs → assert correct extraction of past brands + audience demos + rate ranges

### 3.2 — P1.5 (Brand Deals capture)

**Unit:**
- `tests/unit/services/test_kpi_metric_validation.py` — every kpiMetric has source + as_of
- `tests/unit/services/test_renewal_eligibility_computation.py`

**Integration:**
- 3 ingestion paths (media pack / questionnaire / ad-hoc) write valid `brand_deal` rows
- KPI honesty-floor enforced server-side (not just UI hint)
- main_brand_contact_id FK validates against existing brand_contact rows

**E2E:**
- Onboarded talent → ingest 3 past deals → exported `brand_deals/{talent_id}.json` matches input shape + computed fields

**LLM eval:**
- Media pack → 5 sample media packs → extracted deal records match golden expected shape

### 3.3 — P2 (Brand Discovery)

**Unit:**
- 16 search modules each — input data → expected candidates output
- Qualification signal-weight scoring
- Policy filter: exclusions + warnings
- Deduplication beyond simple name-match

**Integration:**
- Full discovery run: synthetic talent → expected ranked candidates against curated brand_industry_map subset
- Re-engagement timing (Search 1) honours cool_down_override_days + do_not_recontact
- Active exclusivities block competitor brands during window
- social_handles writeback to brand_industry_map (G1 fix)

**E2E:**
- Onboarded talent → discovery_run cron fires → brand_candidates file populated; secondary cron 30 days later → no duplicates; new brand from `last30days` skill appears

**LLM eval:** None for v0.1 (Searches 15/16 are search-driven but evaluated against deterministic web-search responses via cassette).

### 3.4 — P3a (Contact CRM)

**Unit:**
- Decision-role classification heuristic + LLM tagging
- Qualification signal scoring per contact

**Integration:**
- Apollo + LinkedIn + Exa fallback chain in order
- Email verification routing
- DNC enforcement at enrollment-creation time (regardless of talent)

**E2E:**
- Top-N brand_candidates → contact enrichment run → 70%+ verified email rate (against curated test brands)

**LLM eval:**
- Decision-role classification on 20-sample golden set → ≥85% match

### 3.5 — P3b (Outreach)

**Unit:**
- Template selection by decision_role
- Angle evaluation against pitch_angles.json
- Engagement_event MPP filtering (likely_mpp excludes from human_opens count)

**Integration:**
- Smartlead campaign push (mock) per enrollment
- Reply classification webhook → outcomeClassification populated + on `interested` Phase 4 deal created with bidirectional FK setup (G3 fix)
- `pitch_enrollment.created_deal_id` set; `deal.originating_enrollment_id` set; `deal.originating_decision_role_at_pitch` snapshot
- `brand_candidate.status` auto-sync on enrollment + deal state transitions (GAP-06 fix)

**E2E:**
- Onboarded talent → discovery surfaces brand → contact enriched → enrollment created → reply received (`interested`) → deal exists in LEAD with all FKs

**LLM eval:**
- Per-step pitch generation quality: 5 brand × niche combos → assertions on personalization fields used + angle citations + word count
- Reply classification: 20 sample replies → ≥90% match against golden labels (interested / not_interested / needs_more_info / etc.)

### 3.6 — P4 (Deal Lifecycle)

**Unit:**
- State machine transitions (every substage × valid + invalid)
- "Least-progressed wins" delivery substage computation
- `next_action_due_at` reminder cron logic

**Integration:**
- Stage history audit log (append-only; no edits)
- Loss-reason capture on terminal-lost substages
- Bidirectional FK integrity: proposal_pack_ids[], contract_pack_ids[], invoice_pack_ids[], performance_report_pack_ids[]

**E2E:**
- LEAD → PROPOSAL → CONTRACT → DELIVERY → CLOSE manual progression; substage_history sequenced correctly

**LLM eval:** None — Phase 4 skeleton is state-machine logic, not LLM.

### 3.7 — P4.5 (Discovery Prep Pack)

**Unit:**
- Bundle composer per `docs/architecture.md` § 6
- `forked_from_prep_slide_id` traceability

**Integration:**
- Cassette-recorded full pipeline → discovery_prep_pack validates against schema
- Auto-fire on `substage = initial_call_scheduled`
- v1 → v2 NL feedback regen
- Versioned S3 storage layout

**E2E:**
- Onboarded talent + deal in `initial_call_scheduled` → pack auto-fires → 4 artefacts (HTML + PDF + speaker_notes_md + briefing_notes_md) in S3 + DB

**LLM eval (cassette + nightly real):**
- 5 golden scenarios (different talent niches × brand archetypes) → assert: title slide present + talent_overview + audience_snapshot + recent_work (if brand_deals exist) + fit_angle + 3+ proof_point slides + next_steps slide
- briefing_notes_md has 5+ source citations + agenda has 4-6 timed sections + speaker_notes per slide

### 3.8 — P4.6 (Proposal Pack)

**Unit:**
- Discovery debrief 10-field extraction shape
- Commercial gate validation rules
- Brand legal entity capture pathway (O4 fix)

**Integration:**
- 5-stage pipeline (Stage A→E) end-to-end
- Commercial gate HARD BLOCK: slides cannot render until confirmed
- Slide forking from latest prep_pack (forked_from_prep_slide_id correctness)
- negotiation_log bidirectional FK on regen

**E2E:**
- Confirmed prep pack v1 + uploaded brand_brief.pdf → proposal pack v1 generates → agent confirms commercial gate → render artefacts produced → `deal.proposal.*` canonical values populated

**LLM eval (cassette + nightly real):**
- 5 golden scenarios → assert: discovery_debrief 10 fields populated; commercial proposal aligns with talent.working_terms defaults + brand_deal comparable fees; executive_summary 50-80 words; recommendation slide cites at least 2 reasons-to-believe; deliverables/timeline/investment slides structurally complete

### 3.9 — P4.7 (Contract Pack)

**Unit:**
- Merge field source-resolution chain (proposal → talent → agency → brand → discovery_debrief)
- Conditional clause expression evaluator
- Disclosure clause wiring from talent.disclosure_defaults.style (O5 fix)

**Integration:**
- 7-stage pipeline including legal review gate
- Gate enforcement: edits post-approval reset gate (unless trivial_edit_override)
- amendment_log bidirectional FK on regen (G5 fix)
- Brand redline response cycle

**E2E:**
- Confirmed proposal + uploaded brand_legal_info.pdf → contract drafts → reviewer approves → render produces .md + .docx + .pdf → signed PDFs upload writes contract_attachment_id

**LLM eval (cassette + nightly real):**
- 5 golden scenarios → assert: every {{merge_field}} resolved with source + confidence; every {{#if}} block has include/exclude decision + applicability_rationale; narrative_sections each <= max_word_count + cites declared sources

### 3.10 — P4.8 (Invoice Pipeline)

**Unit:**
- Posting detection scoring (5 signals × point values; G1 + G2 fixes applied)
- LLM payment_terms parser (per `docs/invoice_workflow.md` shape)
- Commission FROM-party resolution (4 commission_model enum values)
- Invoice number atomic increment

**Integration:**
- Meta Graph + TikTok detection cron cycles (cassette-recorded responses)
- Per-trigger invoice pack generation (5 trigger_condition enums)
- Multi-invoice schedule under contract_executed → first_post_live → all_deliverables_live progression
- Payment state lifecycle (draft → sent → paid / overdue)
- Overdue reminder cron + payment_reminder_log
- `all_invoices_paid_at` computation triggers correctly

**E2E:**
- Active DELIVERY deal → IG story detection fires → agent confirms match → invoice schedule fires per `contract_executed` trigger → invoice PDF rendered → agent sends → mark-paid endpoint sets payment_state → `all_invoices_paid_at` computed

**LLM eval (cassette + nightly real):**
- Payment terms parsing: 10 sample contract payment terms strings → expected `invoice_schedule[]` shape
- Invoice line-item description quality: 5 deliverable types → assert clear + bill-friendly descriptions

### 3.11 — P4.9 (Performance Report)

**Unit:**
- KPI aggregation (sum vs weighted-avg per metric type)
- Benchmark comparisons math (delta_pct + performance_label rendering)

**Integration:**
- Daily KPI capture cron writes interim_kpi_snapshots
- vs_industry gracefully omits when data/industry_kpi_benchmarks.json absent
- vs_talent_historical averages from filtered brand_deals
- vs_brand_stated_targets reads from discovery_debrief.objectives_heard[]
- final_kpis verbatim populate on agent send
- `final_performance_report_attachment_id` auto-population

**E2E:**
- DELIVERY-stage deal with posted_at set + posting_schedule complete → daily KPI cron accumulates snapshots → window-end auto-fires report → agent sends → 2 of 3 auto-archive conditions met (final_kpis + final_performance_report_attachment_id)

**LLM eval (cassette + nightly real):**
- Narrative quality: 5 golden scenarios → executive_summary 80-120 words + 3+ sources cited; what_worked 3-5 bullets; learnings 2-4 bullets

### 3.A — Auto-archive (loop closure)

**Unit:**
- 3-gate condition logic (all 8 combinations of 3 booleans tested)
- Bidirectional FK setup correctness

**Integration:**
- All 3 conditions met → archive fires
- 2 of 3 conditions met → archive does NOT fire
- Re-fire idempotent (no duplicate brand_deal row)
- KPIs carry verbatim (every field shape preserved)
- Stage transitions to `archived` + is_terminal + is_won

**E2E:**
- M16-level full loop closure test (covered in M16 § 2)

**LLM eval:** None — auto-archive is deterministic.

---

## 4. `nativ test` CLI tool

### 4.1 Design

Test-runner-only Python CLI built with **typer** (modern click). Talks to the running FastAPI service via httpx. Lives at `app/cli/test_cmd.py`; installed as console script `nativ` via pyproject.toml entry point.

```
nativ test                       # show command tree
nativ test --help
nativ test fixtures              # commands for fixtures
nativ test fixtures load synthetic  # load synthetic fixture into running stack
nativ test fixtures load real      # load real fixture from ~/.nativ/test_fixtures/
nativ test fixtures status         # what's currently loaded

nativ test e2e                   # run automated e2e suite
nativ test e2e --phase 4.5       # run e2e for one phase
nativ test e2e --pack prep       # run pack-specific evals

nativ test phase                 # run an interactive phase walkthrough
nativ test phase 0 --agency mercer  # walk through agency setup with the operator
nativ test phase 1 --talent riley   # walk through talent onboarding
nativ test phase 4.5 --deal d_001   # walk through prep pack gen

nativ test eval                  # LLM eval suite
nativ test eval --pack proposal --record   # re-record cassettes
nativ test eval --pack proposal --real     # use real Anthropic API

nativ test smoke                 # smoke tests (health + connectivity)
nativ test smoke vendors         # ping every vendor
nativ test smoke db              # Postgres + Redis + MinIO reachable
nativ test smoke llm             # Anthropic + Langfuse reachable

nativ test report                # generate test report (coverage + LLM costs + perf)
```

### 4.2 Implementation outline

```
app/cli/
  __init__.py
  main.py            # typer app entry point
  test_cmd.py        # nativ test ...
  fixtures.py        # nativ test fixtures ...
  e2e.py             # nativ test e2e ...
  phase.py           # nativ test phase ... (interactive walkthroughs)
  eval.py            # nativ test eval ...
  smoke.py           # nativ test smoke ...
  report.py          # nativ test report ...
  http_client.py     # shared httpx client (talks to local FastAPI)
  fixture_loader.py  # synthetic + real fixture loading
  interactive.py     # prompt_toolkit helpers for phase walkthroughs
```

### 4.3 Interactive phase walkthroughs

`nativ test phase 0 --agency mercer` runs a guided session:

```
$ nativ test phase 0 --agency mercer

Phase 0: Agency Setup walkthrough
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Fixture loaded: 'mercer' (from ~/.nativ/test_fixtures/agencies/mercer.json)

Step 1: Identity + domain
  ✓ agency.name set: "Mercer & Co"
  ✓ agency.domain set: "..."
  Press ENTER to continue → POST /agencies/setup/identity

Step 1.5: Branding
  ✓ logo uploaded
  ✓ colors set
  Press ENTER to continue → POST /agencies/setup/branding

...

Step 6: Mailbox warmup
  Mailbox warmup is started. Background task running.
  Current status: in_progress (0% → 100% over ~2 weeks)
  In a real run, you'd wait. For testing, simulate completion? [Y/n]
  → POST /agencies/setup/test/simulate_warmup_complete

Step 7: Final validation
  Validating against agency_profile.schema.json...
  ✓ All required fields present
  ✓ DNS records verified
  ✓ Warmup status: complete
  ✓ Invoice template configured
  ✓ Commission defaults set
  Phase 0 complete. agency_id: a_550e8400...

Total wall time: 18s
LLM cost: $0.00 (no LLM in Phase 0)
```

### 4.4 Non-interactive scripted runs

`nativ test phase 0 --agency mercer --auto` runs the same flow without prompts, suitable for CI smoke tests.

---

## 5. LLM eval cassette infrastructure

### 5.1 vcrpy setup

```python
# tests/llm_eval/conftest.py

import vcr
from pathlib import Path

llm_cassette = vcr.VCR(
    cassette_library_dir=str(Path(__file__).parent / 'cassettes'),
    record_mode='once',          # record if cassette missing; else replay
    match_on=['method', 'scheme', 'host', 'path', 'body'],
    filter_headers=['authorization', 'x-api-key'],
    filter_query_parameters=['key'],
    decode_compressed_response=True,
)
```

### 5.2 Cassette directory layout

```
tests/llm_eval/cassettes/
  discovery_prep/
    test_briefing_quality__scenario_1_activewear.yaml
    test_briefing_quality__scenario_2_cpg.yaml
    ...
  proposal/
    test_discovery_debrief_extraction__scenario_1.yaml
    ...
  contract/
    test_merge_field_extraction__scenario_1.yaml
    ...
  invoice/
    test_payment_terms_parsing__scenario_1.yaml
    ...
  performance_report/
    test_narrative_quality__scenario_1.yaml
    ...
  outreach/
    test_per_step_generation__scenario_1_buyer.yaml
    ...
  decision_role/
    test_classification__scenario_1_cmo_megabrand.yaml
    ...
```

### 5.3 Re-record discipline

| Trigger | Action |
|---|---|
| Prompt change | Author re-records affected cassettes: `pytest -m llm_eval_record -k {scenario}` |
| Anthropic model upgrade (e.g. Opus 4.7 → 4.8) | Author re-records ALL cassettes via `pytest -m llm_eval_record` |
| Nightly real-LLM eval discovers drift (output diverges >10%) | Sentry alert; author re-records affected scenarios after review |
| New scenario added | Author records once on commit; future runs replay |

### 5.4 Cost telemetry

Every LLM eval test captures `(input_tokens, output_tokens, cost_usd, model)` from the Anthropic response + records to `tests/llm_eval/cost_telemetry.jsonl`. Nightly run aggregates to `reports/llm_cost_nightly.html`.

---

## 6. Synthetic fixture: Acme Talent Agency + Riley Carter

### 6.1 What it includes

**Agency:** `tests/fixtures/synthetic/agency_profile.json`
- name: "Acme Talent Agency"
- domain: "acmetalent.example.com"
- 2 agents (Acme operator + Acme finance)
- Sending mailbox: ed@acmetalent.example.com (warmup complete; mocked)
- Branding: Acme primary blue + secondary cream + Inter font
- Invoice template (markdown): generic Stripe-friendly template
- Commission default: 20% / agency_invoices_brand_pays_talent_net
- Billing entity: "Acme Talent Agency Ltd" UK Ltd

**Talent:** `tests/fixtures/synthetic/talents/riley_carter/`
- name: "Riley Carter"
- platforms: Instagram (250k), TikTok (180k), YouTube (45k) — all with mock oAuth tokens
- content_niches: ["fitness", "wellness", "nutrition"]
- audience_demographics: 70% F / 30% M, 25-34 dominant, US 60% UK 20% AU 8%
- working_terms: 90d default usage, 2 revisions, 48hr approval window
- billing_entity: "Carter Creative LLC" Delaware LLC
- commission_override: none (uses agency default)
- 4 past brand_deals (in `tests/fixtures/synthetic/talents/riley_carter/brand_deals.json`):
  - Lululemon 2024 Q2 (closed, kpis: 95k impressions, 4.2% ER)
  - HelloFresh 2024 Q4 (closed, kpis: 80k impressions, 3.8% ER)
  - Athletic Greens 2025 Q1 (closed, kpis: 120k impressions, 5.1% ER)
  - Manduka 2025 Q3 (closed, kpis: 70k impressions, 4.5% ER)
- contract_template: based on generic_starter.md, adapted for fitness niche

**Brands subset:** `tests/fixtures/synthetic/brand_industry_map_subset.json`
- 30 brands selected from the real 290-brand catalog: activewear + nutrition + wellness + healthtech industries

**In-flight pitch_enrollments:** 3 enrollments at different states (active / responded / interested)

**In-flight deals:** 5 deals at different stages
- d_001: LEAD substage `awaiting_initial_call`
- d_002: LEAD substage `initial_call_scheduled` (triggers Phase 4.5 prep pack)
- d_003: PROPOSAL substage `proposal_sent`
- d_004: CONTRACT substage `signed_pending_kickoff`
- d_005: DELIVERY substage `posts_live_window_open` (triggers Phase 4.8 detection + Phase 4.9 KPI cron)

### 6.2 How CI uses it

Every CI run starts from a clean DB + loads the synthetic fixture via `nativ test fixtures load synthetic`. All synthetic e2e tests run against this state. Total fixture load time: <2s.

---

## 7. Real-data manual testing protocol

### 7.1 Local fixture directory

```
~/.nativ/test_fixtures/
  agencies/
    {agency_id}.json          # operator's real agency_profile (full)
  talents/
    {talent_id}/
      profile.json            # operator's real talent.json (full incl. tokens)
      brand_deals.json        # operator's past brand_deals
  brand_industry_map.json     # symlink to repo's real brand_industry_map.json or override
  README.md                   # operator notes (private)
```

Tests detect presence: `tests/conftest.py` checks if `~/.nativ/test_fixtures/agencies/` is non-empty. If present, `@requires_real_fixture` tests are enabled; otherwise skipped with clear message.

### 7.2 Onboarding the real data (one-time)

```
# 1. Operator copies their real agency_profile.json into ~/.nativ/test_fixtures/agencies/
#    (or generates one via nativ test phase 0 walkthrough with their real data)
mkdir -p ~/.nativ/test_fixtures/agencies
cp /path/to/your/agency_profile.json ~/.nativ/test_fixtures/agencies/

# 2. Same for talent
mkdir -p ~/.nativ/test_fixtures/talents/{talent_id}
cp /path/to/your/talent.json ~/.nativ/test_fixtures/talents/{talent_id}/profile.json

# 3. Verify
nativ test fixtures status
# Output:
#   Real fixtures detected:
#     agencies: 1 (mercer)
#     talents: 1 (riley)  [or whatever the real names are]
#     brand_deals: 4 past deals
```

### 7.3 Hands-on session

```
# Start the stack
docker compose up -d

# Load fixtures
nativ test fixtures load real

# Walk through each phase interactively
nativ test phase 0 --agency mercer
nativ test phase 1 --talent riley
nativ test phase 1.5 --talent riley  # load past brand_deals
nativ test phase 2 --talent riley    # run discovery
nativ test phase 3a --talent riley   # contact enrichment for top-10 candidates
nativ test phase 3b --talent riley   # send outreach (DRY RUN flag)
nativ test phase 4 --deal d_001      # advance a deal
nativ test phase 4.5 --deal d_002    # generate prep pack
nativ test phase 4.6 --deal d_002    # generate proposal
nativ test phase 4.7 --deal d_002    # generate contract
nativ test phase 4.8 --deal d_002    # simulate post detection + generate invoice
nativ test phase 4.9 --deal d_002    # generate performance report
nativ test phase A --deal d_002      # trigger auto-archive

# Or run the whole flow end-to-end non-interactively
nativ test e2e --deal-from-scratch --agency mercer --talent riley --auto
```

### 7.4 Safe-by-default discipline

All real-fixture phases default to safe modes:
- Phase 3b: `--dry-run` ON by default (does NOT actually push to Smartlead; logs would-be sends)
- Phase 4.7: `--no-send` ON by default (doesn't email brand legal team)
- Phase 4.8: `--no-send` ON by default (doesn't send invoice to brand)
- Phase 4.9: `--no-send` ON by default (doesn't send report to brand)

Override with `--allow-real-sends` after operator visual review. Real LLM API calls always happen (Anthropic charges hit; transparent in cost report).

---

## 8. Frontend readiness validation

### 8.1 OpenAPI contract tests

Every API endpoint has a contract test verifying:
- Request shape (Pydantic input model)
- Success response shape (Pydantic output model)
- Each documented error shape + HTTP status
- Authentication required (where applicable)
- Authorisation boundaries (agency_id isolation)
- OpenAPI spec entry exists + matches reality

```python
# tests/contract/test_endpoint_contract_completeness.py

import pytest
from app.main import app

def test_every_endpoint_has_contract_test():
    """CI gate: every endpoint registered in FastAPI must have a corresponding
    contract test. Surfaces missing test coverage early."""
    contract_tested = collect_contract_tested_endpoints()
    registered = [r.path for r in app.routes if r.methods]
    missing = set(registered) - contract_tested
    assert not missing, f"Endpoints without contract tests: {missing}"
```

### 8.2 Stub frontend smoke

`tests/frontend_smoke/` — Vue 3 + Vite project that:
1. Reads `/openapi.json` from the local FastAPI
2. Scaffolds typed TypeScript clients via `openapi-typescript`
3. Implements ONE critical UI flow (the agency setup wizard) using the generated client
4. Renders the wizard headlessly via Playwright
5. Walks through all 9 setup steps end-to-end via simulated user input
6. Asserts on each step's success + final state

Run via `nativ test e2e --frontend-smoke`. ~30s per run. Catches "this endpoint isn't UI-shaped" issues early.

Subsequent phases get one stub-frontend smoke per critical flow:
- P1: talent onboarding wizard
- P4.5: prep pack viewer + agent NL feedback box
- P4.6: proposal pack viewer + commercial gate UI
- P4.7: contract pack viewer + legal review gate UI

### 8.3 What the frontend smoke verifies

- Every endpoint returns JSON-serialisable data (no datetime tuples; UUIDs as strings; etc.)
- Error responses match documented schema (`{"detail": "...", "code": "..."}`)
- Long-running operations return immediately with task_id + status polling endpoint
- File uploads use multipart/form-data with documented field names
- Webhook receivers are clearly separated from agent-facing endpoints (different prefix path)

---

## 9. CI pipeline

### 9.1 Workflow file structure

```
.github/workflows/
  test.yml              # PR gate
  test-main.yml         # post-merge
  test-nightly.yml      # 02:00 UTC daily
  test-release.yml      # on tag push
```

### 9.2 Stages (`test.yml` — PR gate)

```yaml
jobs:
  lint-and-format:
    steps:
      - ruff check . --output-format=github
      - ruff format --check .
      - pyright

  schemas:
    steps:
      - python scripts/verify_pydantic_codegen.py  # drift check
      - pytest tests/unit/schemas/ tests/integration/test_schema_roundtrip.py

  unit:
    steps:
      - pytest tests/unit/ --cov=app --cov-fail-under=100 --cov-report=xml

  integration:
    services:
      - postgres:16
      - redis:7
      - minio
    steps:
      - alembic upgrade head
      - pytest tests/integration/ --cov-append

  api-contract:
    services: [postgres, redis, minio]
    steps:
      - pytest tests/contract/

  webhook:
    services: [postgres, redis]
    steps:
      - pytest tests/webhook_receivers/

  state-machine:
    steps:
      - pytest tests/state_machine/

  llm-eval-cassette:
    services: [postgres, redis, minio]
    steps:
      - pytest tests/llm_eval/ -m "not record"

  e2e-cassette:
    services: [postgres, redis, minio]
    steps:
      - pytest tests/e2e/

  frontend-smoke:
    services: [postgres, redis, minio]
    steps:
      - cd tests/frontend_smoke && pnpm install && pnpm test
```

### 9.3 Nightly (`test-nightly.yml`)

```yaml
jobs:
  llm-eval-real:
    if: ${{ secrets.ANTHROPIC_API_KEY }}
    steps:
      - export ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY
      - pytest tests/llm_eval/ -m "live" --budget=$25
      - python scripts/llm_cost_report.py >> reports/nightly_cost.html

  performance-smoke:
    services: [postgres, redis]
    steps:
      - pytest tests/performance/ -m "smoke"

  live-vendor-smoke:
    if: ${{ secrets.SMARTLEAD_API_KEY }}
    steps:
      - pytest tests/live/ -m "live"
```

### 9.4 Budget gating

LLM eval real-mode runs are budget-gated. The `--budget=$25` flag aborts the nightly run if cumulative cost exceeds the threshold (graceful skip + Sentry alert).

---

## 10. Test infrastructure deliverables

What needs to exist in the repo to enable the test plan:

```
tests/
  conftest.py                       # session-scoped fixtures (Postgres, Redis, MinIO, mocks)
  pytest.ini                        # markers + coverage config
  factories/                        # factory_boy per schema
    __init__.py
    agency_profile.py
    talent.py
    brand_candidate.py
    ... (one per schema)
  unit/
    schemas/
    services/
    agents/
    utils/
  integration/
    api/
    services/
    agents/
    vendors/
    tasks/
    webhooks/
  contract/                         # OpenAPI contract tests per endpoint
  webhook_receivers/                # signature + idempotency tests
  state_machine/                    # transition coverage
  llm_eval/
    conftest.py                     # vcrpy config
    cassettes/                      # recorded cassettes
    discovery_prep/
    proposal/
    contract/
    invoice/
    performance_report/
    outreach/
    decision_role/
  e2e/                              # full pipeline scenarios
  frontend_smoke/                   # Vue 3 + Vite + Playwright
    package.json
    src/
    playwright.config.ts
  fixtures/
    synthetic/                      # Acme + Riley + 30 brands
      agency_profile.json
      brand_industry_map_subset.json
      talents/
        riley_carter/
          profile.json
          brand_deals.json
      pitch_enrollments.json
      deals.json
  performance/                      # Locust files + benchmarks
  security/                         # secret leakage / authz / etc.
  skip_handling/                    # per-phase skip-tolerance tests
  live/                             # env-gated real-vendor tests
    vendors/

scripts/
  verify_pydantic_codegen.py
  anonymise_fixtures.py
  llm_cost_report.py
  perf_report.py

.github/workflows/
  test.yml
  test-main.yml
  test-nightly.yml
  test-release.yml
```

---

## 11. Build order

The test plan accretes alongside the project plan milestones (see § 1.5 + § 2). High-level:

| Project plan milestone | Tests added | Test deliverable |
|---|---|---|
| M0 | Foundation | conftest.py + factories + CI workflow stubs |
| M1 | Schema round-trip + Alembic + pgcrypto + repository tests | First production tests |
| M2 | Agent base + skill subagent + tool catalog + bundle composer + memo store tests | Agent layer covered |
| M3 | Per-vendor wrapper tests (7 vendors × mock + live) | Vendor layer covered |
| M4-M10 | Phase-specific tests per § 3 | Phase 0-4 covered |
| M11 | First LLM eval cassettes; first e2e (P4.5) | LLM eval infra live |
| M12-M15 | LLM eval cassettes per pack + per-pack e2e | All pack phases covered |
| M16 | Full loop closure e2e | v0.1 ready |
| M17 | Performance + security + load tests | Production hardening |

`nativ test` CLI tool delivers in M2 (foundation), expands per milestone.

---

## 12. v0.1 test completion criteria

The backend ships when:
- All CI gates green
- 100% coverage per § 1.1 metrics
- LLM eval cassettes cover every pack type's 5+ golden scenarios
- Real-LLM nightly run pass rate >95% for 7 consecutive nights
- `nativ test e2e --deal-from-scratch --agency mercer --talent riley --auto` runs end-to-end with real LLM + writes a fully-archived brand_deal record at completion
- OpenAPI stub frontend wizard runs headless without errors
- Performance: p95 endpoint latency <500ms (LLM-excluded); 50 concurrent deals supported
- Security: 0 critical findings from secret leakage + dependency vuln + authz boundary scans
