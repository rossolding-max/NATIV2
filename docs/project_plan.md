# Project Plan — Backend Build

**Status:** Locked v0.1 (2026-05-26). Dependency-ordered milestones (no timelines per locked decision). Pairs with `docs/architecture.md` for the "what"; this is the "how".

**Approach:** foundation first, then phases sequentially with explicit handoff + interdependency checks at each phase boundary. Every phase ships with skip-handling tests so downstream phases tolerate missing upstream data.

---

## Milestone overview

| # | Milestone | Unlocks |
|---|---|---|
| M0 | Repo foundation | Everything below |
| M1 | Data layer (all 17 schemas → ORM) | M2 + all phase work |
| M2 | Agent infrastructure (Claude Agent SDK + memo store) | M11-M15 |
| M3 | Vendor wrappers (Smartlead, Exa, Apollo, LinkedIn, Meta Graph, TikTok) | M4-M9 + M14 |
| M4 | Phase 0 (Agency Setup) | M5-M15 |
| M5 | Phase 1 (Talent Onboarding) | M6-M15 |
| M6 | Phase 1.5 (Brand Deals capture) | M11 + M15 |
| M7 | Phase 2 (Brand Discovery) | M8 + M11 |
| M8 | Phase 3a (Contact CRM) | M9 |
| M9 | Phase 3b (Outreach) | M10 |
| M10 | Phase 4 (Deal Lifecycle skeleton) | M11-M16 |
| M11 | Phase 4.5 (Discovery Prep Pack) — first AI pack ⭐ | M12 |
| M12 | Phase 4.6 (Proposal Pack) | M13 |
| M13 | Phase 4.7 (Contract Pack) | M14 |
| M14 | Phase 4.8 (Invoice Pipeline) | M16 |
| M15 | Phase 4.9 (Performance Report) | M16 |
| M16 | Auto-archive loop closure | v0.1 complete |
| M17 | Production hardening | v2 prep |

Each milestone documented below with: inputs (what must exist) + outputs (deliverables) + acceptance (how we know it works) + skip-handling notes.

---

## M0 — Repo foundation

**Inputs:** existing spec (17 schemas — 16 domain + 1 shared `kpi_metric` — + 15 workflow docs).

**Outputs:**
- `pyproject.toml` (Poetry or uv)
- `docker-compose.yml`: FastAPI + Celery worker + Celery beat + Postgres + Redis + MinIO + Langfuse
- `app/` skeleton: `app/api/`, `app/agents/`, `app/models/`, `app/vendors/`, `app/services/`, `app/tasks/`, `app/utils/`
- Alembic init; first migration (empty)
- `app/main.py` FastAPI app with health endpoint + Sentry init
- `app/celery_app.py` with 2 queues registered (`default`, `llm_heavy`) + Beat schedule stub. v2 adds `vendor_apis` + `rendering` per V2-SCALE-01.
- `tests/` skeleton with pytest config
- GitHub Actions CI: lint (ruff) + typecheck (pyright) + tests + datamodel-code-generator drift check
- `.env.example` with all env vars enumerated

**Acceptance:** `docker compose up` brings stack up; health endpoint returns 200; sample Celery task runs; tests pass.

**Skip notes:** N/A (foundation milestone).

---

## M1 — Data layer (all 17 schemas → ORM)

**Inputs:** M0.

**Outputs:**
- `app/models/pydantic/` auto-generated from all 17 schemas (16 domain + 1 shared)
- `app/models/sqla/` hand-written for: `agency_profile`, `talent`, `brand_industry_map`, `brand_candidate`, `brand_contact`, `brand_deal`, `pitch_template`, `pitch_angle`, `pitch_enrollment`, `deal`, `discovery_prep_pack`, `proposal_pack`, `contract_pack`, `invoice_pack`, `performance_report_pack`, `memo`
- Alembic migration applying all tables with indexes + pgcrypto extension
- `app/utils/encryption.py` (pgcrypto wrappers for sensitive columns)
- Repository pattern: `app/repositories/` with async CRUD per model
- Tests: round-trip Pydantic ↔ SQLAlchemy ↔ JSON Schema for every model

**Acceptance:** load existing `data/brand_industry_map.json` into Postgres via import script; all 290 records persisted and re-readable.

**Skip notes:** N/A (foundation).

**Interdependency checks before next milestone:**
- All 17 schemas (16 domain + 1 shared) have corresponding Pydantic + SQLAlchemy models
- `pgcrypto` extension installed; encryption helpers tested
- Multi-tenant-ready: every domain table has `agency_id` UUID column
- Pack tables enforce uniqueness on `(deal_id, version)` where applicable

---

## M2 — Agent infrastructure (Claude Agent SDK baseline)

**Inputs:** M1.

**Outputs:**
- `app/agents/base.py`: base `Agent` class wrapping Claude Agent SDK; standardised invocation (input bundle → output) + Langfuse instrumentation
- `app/agents/coordinator.py`: `DealOrchestratorAgent` base class
- `app/agents/skills/researcher.py`, `writer.py`, `extractor.py`, `renderer.py` (skill specialist agents)
- `app/agents/tools/`: shared tool catalog
  - `get_talent(talent_id)`, `get_deal(deal_id)`, `get_brand_record(brand_id)`
  - `get_brand_deals_filtered(...)`, `get_top_pitch_angles(...)`
  - `write_memo(...)`, `read_memos(...)` ← memo store core
  - `validate_schema(payload, schema_id)`, `render_template(...)`
- `app/agents/bundles.py`: context bundle composers (per-pack-type bundle assembly per `docs/architecture.md` § 6)
- Langfuse instrumentation wired into every agent call
- Memo store: full `write_memo` + `read_memos` SQL implementation with tag-filter retrieval

**Acceptance:** smoke test — invoke `DealOrchestratorAgent` with a minimal context bundle + simple prompt; agent calls `read_memos`, then `write_memo`, returns; Langfuse trace captured.

**Skip notes:** N/A (foundation).

**Interdependency checks:**
- All 4 skill subagents instantiable + share tool catalog access
- Memo writes produce valid `memo.schema.json` payloads
- Memo reads return matching tag filters deterministically
- Prompt caching is exercised (verify cached_tokens > 0 on second pass)

---

## M3 — Vendor wrappers

**Inputs:** M2 (for the agent SDK config; other vendor wrappers don't strictly depend on agent work).

**Parallel-with-M2 note:** M3 can start in parallel with M2 once the vendor list is locked. Smartlead / Exa / Apollo / LinkedIn / Meta Graph / TikTok wrappers don't depend on agent infrastructure (researcher / writer / extractor / renderer); they're consumed BY the agents but built independently. Run them on a separate workstream if team has capacity.

**Outputs:**
- `app/vendors/anthropic_client.py` (centralises Anthropic SDK config + cost tracking)
- `app/vendors/smartlead.py` — campaigns / leads / sequences / webhook signature validation
- `app/vendors/exa.py` — search / findSimilar / contents endpoints
- `app/vendors/apollo.py` — people-by-domain + filters
- `app/vendors/linkedin.py` — profile + last-activity reads
- `app/vendors/meta_graph.py` — oAuth flow + /me/media + /{ig-media-id}/insights + /me/stories
- `app/vendors/tiktok.py` — oAuth flow + /v2/video/list/ + /v2/video/query/
- Every wrapper: rate-limit policy, retry-with-backoff, `respx` mock support, sentry breadcrumb on each call

**Acceptance:** each vendor has integration tests against mocked endpoints. `live_tests/` directory gated by env flag with live-call smoke tests for each vendor.

**Skip notes:** N/A (foundation); vendor outages tolerated by retry + downstream skip-handling.

**Interdependency checks:**
- Rate-limit budgets configured in Redis counters
- All env vars present + redacted in logs
- oAuth flows tested end-to-end (Meta + TikTok)

---

## M4 — Phase 0 (Agency Setup)

**Inputs:** M1-M3.

**Outputs:**
- `app/api/agencies.py`: POST/PATCH endpoints implementing the 9-step setup (per `docs/agency_setup_workflow.md`)
- `app/services/dns_validation.py`: Smartlead-backed DNS record validation
- `app/services/branding.py`: branding asset upload to S3 (presigned PUT URLs)
- `app/services/invoice_template.py`: starter template + atomic sequence counter (Postgres `SELECT … FOR UPDATE`)
- `app/services/agency_warmup.py`: Smartlead warmup status sync (Celery task)
- Commission defaults capture (`default_commission_rate` + `default_commission_model`)
- Tests: end-to-end agency setup happy path (Smartlead mocked); validation rejects incomplete setups

**Acceptance:** real agency setup completed; `agency_profile` row in Postgres with branding + invoice template + commission defaults populated; mailbox warmed.

**Skip notes:** Phase 0 cannot be skipped — it's the prerequisite to everything.

**Interdependency checks:**
- DNS records SPF/DKIM/DMARC all verified before `status: active`
- `branding` block populated with at minimum logo_url + primary_color + font families
- `invoice_template.invoice_number_sequence` initialised
- `default_commission_*` fields set

---

## M5 — Phase 1 (Talent Onboarding)

**Inputs:** M4.

**Outputs:**
- `app/api/talents.py`: POST/PATCH endpoints implementing the 8-step onboarding (per `docs/onboarding_workflow.md`)
- `app/services/talent_seed.py` (Step 1)
- `app/services/platform_oauth.py` (Step 2): full oAuth flows for Meta + TikTok + YouTube; token storage via `pgcrypto`; validation gate (test API call per platform with scope check)
- `app/services/media_pack_extraction.py` (Step 3): pypdf + python-docx + LLM extraction (uses `extractor` subagent)
- `app/services/questionnaire.py` (Step 5): adaptive questionnaire including `commission_override` + `invoice_payment_override`
- `app/services/contract_template_setup.py` (Step 7.5): starter template adoption + validation (every `{{merge_field}}` has a definition; every `{{#if}}` has a rule; dry-run compose passes)
- Tests: full talent onboarding happy path; oAuth validation gate failure path; skip-step tolerance

**Acceptance:** real talent onboarded; all platforms connected with scope-validated tokens; `contract_template` ready for downstream contract pack generation.

**Skip notes:** individual onboarding steps can be skipped (deferred to "complete later" backlog); downstream features degrade gracefully if e.g. `working_terms.default_usage_rights` is missing.

**Interdependency checks:**
- `talent.platforms[].api_credentials.access_token_ref` populated + decryptable + scope-validated
- `talent.commission_override` either populated or explicitly defaulted to agency defaults
- `talent.contract_template` validates against schema; dry-run compose succeeds
- `talent.billing_entity.legal_name` set (required for invoicing)

---

## M6 — Phase 1.5 (Brand Deals capture)

**Inputs:** M5.

**Outputs:**
- `app/api/brand_deals.py`: CRUD + ingestion endpoints
- 3 ingestion paths (per `docs/brand_deals_workflow.md`): media pack extraction, questionnaire-guided entry, ad-hoc add
- KPI honesty-floor enforcement (every metric has `source` + `as_of`)
- `app/services/kpi_validation.py`: validates kpiMetric shape + flags suspicious values

**Acceptance:** real talent's past deals imported; per-talent `data/brand_deals/{talent_id}.json` shape preserved in DB.

**Skip notes:** if skipped, M11 prep pack lacks comparable case studies (omits "Recent work" slide); M15 performance report lacks `vs_talent_historical` benchmark (omitted with note).

**Interdependency checks:**
- Every populated KPI has `source` enum + `as_of` date
- `outcome` enum populated per deal
- `main_brand_contact_id` references valid `brand_contact` rows where applicable

---

## M7 — Phase 2 (Brand Discovery)

**Inputs:** M6 + M3.

**Outputs:**
- `app/services/discovery/`: per-search modules (Search 1-16 from `docs/brand_discovery.md`)
- `app/services/qualification.py`: signal-based qualification scoring (per `schemas/brand_candidates.schema.json` qualificationSignal)
- `app/services/policy_filter.py`: exclusions (blocked_industries, active_exclusivities) + warnings (sensitive_category, etc.)
- `app/tasks/discovery_run.py`: Celery task firing monthly per talent
- `app/services/brand_enrichment.py`: refreshes `brand_industry_map` + **captures `social_handles` per platform** (audit Tier 1 G1 fix)

**Acceptance:** discovery run for real talent produces ranked candidates file (`data/brand_candidates/current/{talent_id}.json`); brand_industry_map updates with social_handles for newly discovered brands.

**Skip notes:** if skipped, agent manually creates `brand_candidate` rows on-demand when starting outreach; downstream Phase 4.8 detection degrades if `brand.social_handles` absent for that brand.

**Interdependency checks:**
- `brand_industry_map.brands[].social_handles` populated for top-50 active brands (refresh weekly via cron)
- `brand_candidate.qualification.score` >= 0.30 for all `tier: primary` candidates
- Active exclusivities correctly filter brands

---

## M8 — Phase 3a (Contact CRM)

**Inputs:** M7.

**Outputs:**
- `app/services/contact_enrichment.py`: Apollo + LinkedIn enrichment per `docs/contact_enrichment_workflow.md`
- `app/services/decision_role.py`: classification heuristic + LLM tagging (decision_role enum)
- `app/api/brand_contacts.py`: CRUD + enrichment trigger endpoints
- Honour-opt-out hygiene: `do_not_contact` enforced across all enrollment creation paths

**Acceptance:** contacts surfaced for top-N brand_candidates; verified email rate > 70%; `decision_role` populated with rationale.

**Skip notes:** if skipped, agent manually enters contact details when creating enrollment; `decision_role` defaulted to `unknown`.

**Interdependency checks:**
- Every contact has `decision_role` + `decision_role_rationale`
- `qualification` signals + tier populated per contact
- `do_not_contact` + `opt_out_at` honoured across talents (shared roster contact pool)

---

## M9 — Phase 3b (Outreach)

**Inputs:** M8.

**Outputs:**
- `app/services/outreach/`: template selection + angle evaluation (per `docs/outreach_workflow.md`) + per-step AI generation
- `app/agents/outreach_generator.py`: uses `writer` subagent
- Smartlead push (campaign + leads + step content)
- Webhook handlers: `POST /webhooks/smartlead/email_event` + `POST /webhooks/smartlead/reply`
- Reply classification: dedicated classifier prompt (Opus 4.7 per locked LLM tier)
- `app/tasks/enrollment_state_sync.py`: 5-min Celery task syncing Smartlead state
- **Audit Tier 1 G3 fix:** on `interested` reply, create Phase 4 deal + bidirectionally set `pitch_enrollment.created_deal_id` ↔ `deal.originating_enrollment_id` + populate `deal.originating_decision_role_at_pitch`
- Analytics aggregation script (`scripts/analyze_outreach.py` already exists; extends with funnel-to-deal metrics)

**Acceptance:** real outreach campaign sent; replies received; classifier accuracy >85% on labelled test set; `interested` reply triggers deal creation with full bidirectional FK setup.

**Skip notes:** if skipped, agent manually creates Phase 4 deals in LEAD; `originating_enrollment_id` null on those deals.

**Interdependency checks:**
- Every sent email has full `pitch_enrollment.steps[].generation_meta` provenance (angles_used, personalization_fields_used, prompt_hash)
- Reply classification populates `outcomeClassification.extracted_signals` (asked_for_meeting / pricing / etc.)
- `brand_contact.pitchHistoryEntry.enrollment_id` populated as denormalised index

---

## M10 — Phase 4 (Deal Lifecycle skeleton)

**Inputs:** M9.

**Outputs:**
- `app/api/deals.py`: CRUD + state transition endpoints
- `app/services/deal_state_machine.py`: enforces valid substage transitions per `docs/deal_lifecycle_workflow.md` § State machine
- Stage history audit log (append-only `stage_history[]`)
- Next-action reminder cron (daily; finds overdue `next_action_due_at`; surfaces to agent)
- Loss-reason capture + analytics: `loss.reason` × `lost_at_stage` cross-tab
- Per-deliverable vs deal-level state computation (audit Tier 2 R4 fix — "least-progressed wins" rule)

**Acceptance:** deals progress through LEAD → PROPOSAL → CONTRACT → DELIVERY → CLOSE manually via API; invalid transitions rejected; lost deals tagged with structured reasons.

**Skip notes:** N/A (Phase 4 is required for any pack work).

**Interdependency checks:**
- State machine table (31 substages) fully implemented
- `deal.proposal.negotiation_log[].proposal_pack_version` bidirectional with proposal pack versions
- `deal.contract.amendment_log[].contract_pack_version` bidirectional with contract pack versions
- `deal.delivery.campaign_hashtags[]` field accepts agent input (audit Tier 1 G2 fix)

---

## M11 — Phase 4.5 (Discovery Prep Pack) ⭐ first AI pack

**Inputs:** M10 + M2.

**Outputs:**
- `app/agents/packs/discovery_prep.py`: pack-specific coordinator
- Composes `researcher` (Exa brand research) + `writer` (briefing + agenda + slide content as markdown). **Renderer subagent NOT engaged in v0.1** — slide visual rendering deferred to v2 (V2-PACK-01); first invoked in M12 / proposal pack.
- 3-pass Opus 4.7 generation with prompt-caching across passes
- NL feedback regeneration loop (v1, v2, v3 versioning per `docs/discovery_prep_workflow.md`)
- Auto-fire on `substage = initial_call_scheduled` (Celery scheduled task `phase_4_5_auto_fire`)
- Versioned storage in S3 + Postgres
- v0.1 deliverables: `briefing-notes.md` + `agenda.md` + `speaker-notes.md` + `slides.md` (all slide content concatenated as markdown — agent reads pre-call). HTML/PDF/PPTX deferred to v2.

**Acceptance:** real deal in `initial_call_scheduled` fires real prep pack generation; 4 markdown deliverables produced + stored in S3; agent NL feedback produces v2; memo written summarising prep-pack-generation learnings (visible in subsequent `read_memos` calls).

**Skip notes:** if skipped, agent goes into discovery call without auto-drafted pack; `deal.lead.discovery_call_notes` captured manually post-call.

**Interdependency checks:**
- Coordinator + 3 LLM subagents (researcher + writer + extractor as needed) successfully compose (multi-pass; prompt cache hits)
- Memo store writes from `researcher` (brand observations) + `writer` (talent learnings) round-trip readable
- Context bundle composer + augment tools both exercised in real generation
- Langfuse trace shows full multi-agent span tree

**This is the foundational AI pack — proves the entire agent architecture for v0.1 (coordinator + skill subagents + memo store + context bundles + Langfuse instrumentation).** Subsequent packs (M12-M15) reuse the same skill subagents with different compositions; M12 (proposal pack) is where the renderer subagent first ships.

---

## M12 — Phase 4.6 (Proposal Pack)

**Inputs:** M11.

**Outputs:**
- `app/agents/packs/proposal.py`: 5-stage pipeline (per `docs/proposal_pack_workflow.md`)
  - Stage A: context augmentation (file uploads → `extractor` subagent)
  - Stage B: hybrid discovery debrief extraction → `deal.lead.discovery_debrief`
  - Stage C: commercial gate (LLM proposes; agent must confirm before render — HARD GATE)
  - Stage D: 3-pass slide generation
  - Stage E: render
- Commercial gate UI endpoints + hard-block-render-until-confirmed enforcement
- **Audit Tier 2 O4 fix:** brand legal entity proactive capture pathway (commercial gate warns if missing)

**Acceptance:** proposal pack for real deal with brand brief upload; commercial gate enforced (slides cannot render until confirmed); brand legal entity warning surfaces when missing; bidirectional link to `deal.proposal.negotiation_log[].proposal_pack_version` populated on every regen.

**Skip notes:** if skipped, agent uploads their own proposal PDF as `proposal_attachment_id`; `deal.proposal` commercial fields entered manually.

**Interdependency checks:**
- Forked slides reference `forked_from_prep_slide_id` correctly
- `discovery_debrief` 10-field structure populated + agent-confirmed before commercial gate
- Commercial confirmation writes to `deal.proposal.*` canonical fields + sets `commercial_confirmed_at`
- Memos written during proposal generation tagged with both `deal_id` AND `brand_id` (for future cross-deal retrieval)

---

## M13 — Phase 4.7 (Contract Pack)

**Inputs:** M12.

**Outputs:**
- `app/agents/packs/contract.py`: 7-stage pipeline (per `docs/contract_pack_workflow.md`)
  - Stage A: context augmentation (brand legal info uploads → `extractor`)
  - Stage B: merge field extraction (talent.billing_entity + agency_profile + deal.proposal.* → values with confidence + source)
  - Stage C: conditional clause evaluation (LLM per `{{#if}}` block)
  - Stage D: narrative drafting (LLM fills `{{narrative_*}}`)
  - Stage E: compose markdown
  - Stage F: HARD LEGAL REVIEW GATE (blocking_issues auto-populated; previous_approvals audit)
  - Stage G: render (markdown + Word + PDF)
- **Audit Tier 1 G5 fix:** bidirectional `amendment_log[].contract_pack_version` ↔ `contract_pack.generation.amendment_log_entry_ref`
- **Audit Tier 2 O5 fix:** disclosure clause wired into contract template via `{{disclosure_style}}` merge field from `talent.disclosure_defaults.style`
- Brand redline response handling (`trigger: brand_redline_response`)

**Acceptance:** contract drafted from real confirmed proposal; legal review gate enforced; signed PDFs round-trip into `contract_attachment_id`; amendment workflow tested with bidirectional FK setup.

**Skip notes:** if skipped, agent uploads signed contract PDF directly; `draft_contract_attachment_id` never set.

**Interdependency checks:**
- Legal review gate: edits post-approval reset gate (or `trivial_edit_override` honoured)
- `legal_review.previous_approvals[]` audit trail captures every approve/edit cycle
- Disclosure clause present in every rendered contract
- python-docx fallback for markdown tables tested

---

## M14 — Phase 4.8 (Invoice Pipeline)

**Inputs:** M13.

**Outputs:**
- `app/services/posting_detection.py`: scoring algorithm (per `docs/invoice_workflow.md` § Layer 1) + Meta Graph + TikTok polling crons (`poll_phase_4_8_detection_*`)
- `app/services/payment_terms_parser.py`: LLM-parse of `contract_pack.commercial_proposal.payment_terms` → `invoice_schedule[]` (one-time agent gate)
- `app/agents/packs/invoice.py`: lighter agent (1-2 LLM passes per invoice)
- Multi-invoice schedule with `trigger_condition` enum (contract_executed / first_post_live / all_deliverables_live / specific_date / manual)
- Commission split (FROM-party determination per locked design — agency_invoices_brand_pays_talent_net default)
- Overdue reminder cron (`invoice_overdue_reminders`)
- **Audit Tier 1 G1 fix:** `brand_industry_map.brands[].social_handles` consumed in scoring algorithm
- **Audit Tier 1 G2 fix:** `deal.delivery.campaign_hashtags[]` consumed in scoring algorithm

**Acceptance:** real post detected via Meta Graph polling; agent confirms match (UI surfaces `posted_detection.match_signals` + `match_score`); invoice schedule fires; invoice PDF rendered + sent manually (v0.1).

**Skip notes:** if skipped, agent enters post URLs manually; agent creates invoice records manually with PDF upload; `payment_received_at` set manually.

**Interdependency checks:**
- Detection cron polls only active DELIVERY-stage deals (efficiency)
- `posted_detection.method` enum correctly tagged per match
- Invoice numbering atomic counter increments per-agency (no collisions)
- Commission model resolution: `talent.commission_override` overrides `agency_profile.default_*` correctly

---

## M15 — Phase 4.9 (Performance Report)

**Inputs:** M14.

**Outputs:**
- `app/tasks/kpi_capture_cron.py`: daily cron writing per-post snapshots to `deal.delivery.interim_kpi_snapshots[]` (audit Tier 1 R1 covered)
- `app/agents/packs/performance_report.py`: aggregation (interim snapshots → final kpis{}) + benchmarks + narrative (per `docs/performance_report_workflow.md`)
- 3 benchmark comparisons: vs_industry (omitted in v0.1 — benchmark file is v2), vs_talent_historical (averaged from `brand_deals`), vs_brand_stated_targets (extracted from `discovery_debrief`)
- Soft agent gate; on send auto-populates `deal.close.final_performance_report_attachment_id` + `final_kpis`
- `kpi_refresh` regen trigger for late-reporting platform data

**Acceptance:** real deal in `performance_window` has daily KPI snapshots accumulating; on window end, report auto-fires; agent sends → final_kpis populated; auto-archive check unlocks.

**Skip notes:** if skipped, agent uploads report PDF manually + enters `final_kpis` via UI form; auto-archive can still fire if invoice condition also met.

**Interdependency checks:**
- KPI cron handles oAuth token expiry gracefully (surface "Reconnect needed" prompt)
- Aggregate `kpis{}` math correct (sum where summable; weighted-avg where rate-based)
- Benchmark `delta_pct` + `performance_label` rendered into composed markdown
- Memos written summarising "what worked" learnings (cross-deal retrieval surface)

---

## M16 — Auto-archive loop closure

**Inputs:** M15.

**Outputs:**
- `app/tasks/auto_archive_check.py`: 15-min cron
- Builds Phase 1.5 brand_deal record from won deal data (deliverables + fee + usage_rights + kpis verbatim from `deal.close.final_kpis`)
- Bidirectional FK setup: `brand_deal.originated_from_pitch_enrollment_id` ← `deal.originating_enrollment_id`; `brand_deal.archived_from_deal_id` ← `deal.deal_id`
- Sets `deal.close.archived_to_brand_deal_id` + `archived_at`
- Marks deal `archived` (stage + substage + `is_terminal: true` + `is_won: true`)

**Acceptance:** real deal hits all three conditions (all_invoices_paid_at + final_kpis + final_performance_report_attachment_id) → auto-archive fires; `brand_deals/{talent_id}.json` gains new entry; loop closes; deal removed from active pipeline view.

**Skip notes:** N/A (auto-archive is required for v0.1 completion).

**Interdependency checks:**
- All three gate conditions verified server-side (no client can short-circuit)
- Bidirectional FKs validate on both ends
- KPIs carry over without data loss (kpiMetric shape preserved verbatim)
- Memos tagged with both new `brand_deal.deal_id` AND old `deal_pipeline_*` id for retrieval continuity

---

## M17 — Production hardening (v2 prep)

**Inputs:** M16.

**Outputs:**
- Per-vendor rate limit policies + circuit breakers (Anthropic, Meta Graph, TikTok, Apollo, Exa)
- Retry/backoff hardening for all Celery tasks (exponential backoff; max-retries per task)
- LLM cost dashboards (Langfuse + custom Postgres rollups per agency/talent/deal/pack-type)
- Performance perf tuning (slow query log review; index tuning; Redis cache hit rates)
- Security audit: secret leakage scanning (e.g. truffleHog), IAM review, dependency vulnerability scan (e.g. safety/dependabot)
- Load test: simulate 50 concurrent deals across 10 talents (Locust)
- Deployment artefacts: production Dockerfile (multi-stage build); deployment doc for v2 hosting decision (Vercel for frontend; backend host TBD — Railway / Fly.io / AWS evaluated separately)
- Migration plan: filesystem JSON → Postgres for any agency that pre-existed v0.1

**Acceptance:** all integration tests pass under load; no critical security findings; cost dashboards operational; deployment doc reviewable.

**Skip notes:** N/A (production hardening).

---

## Cross-cutting concerns (apply across all milestones)

### Testing discipline

| Test type | When | Coverage target |
|---|---|---|
| Unit tests | Every PR | 80%+ for services + models; 100% for repository CRUD + state machines |
| Integration tests | Every PR | Every API endpoint; every webhook receiver; every Celery task |
| LLM evaluation tests | Per pack milestone (M11-M15) | Golden test sets per pack type: prompt + context bundle → expected output shape + key field presence. Run nightly against latest Opus. |
| Schema round-trip tests | Every PR (via CI hook) | Every Pydantic model validates against its JSON schema |
| Live smoke tests | Manual / pre-deploy | One end-to-end happy-path run with real vendor APIs (gated by env flag) |

### Memo store discipline

Every milestone that ships an agent (M11-M15) MUST:
1. Define which memos that agent writes (memo_type + scope + topic conventions)
2. Define which memos that agent reads (filter shape per use case)
3. Write integration tests verifying memo round-trip
4. Document the memo conventions in the corresponding `docs/{phase}_workflow.md`

### Schema migration discipline

Any milestone that needs a schema change:
1. Edit `schemas/{schema}.schema.json`
2. Bump the schema $id version
3. Regenerate Pydantic via `datamodel-code-generator`
4. Hand-write SQLAlchemy migration; generate Alembic revision
5. Verify Pydantic ↔ SQLAlchemy ↔ JSON Schema round-trip in tests
6. Update the corresponding `docs/` workflow doc

### Observability discipline

Every Celery task + every agent invocation:
- Carries a correlation ID propagated via task headers
- Reports start/end events to Sentry (breadcrumbs)
- Wraps LLM calls in Langfuse spans with metadata (pack_id, subagent, pass_name)
- Emits structured log line on entry/exit with cost (where applicable)

### Skip-handling discipline

For every phase (M4-M15):
- Document "if this phase is skipped" behaviour in `docs/{phase}_workflow.md` (already done — audit Tier 1)
- Implement skip-handling code paths in downstream phases (e.g. M11 prep pack handles empty `brand_deals` gracefully)
- Test skip-handling in integration tests (deal with no brand_candidates → manual brand input path tested)

---

## v0.1 completion criteria

v0.1 ships when:
- M0-M16 complete
- A real end-to-end deal flows from outreach reply → prep pack → proposal → contract → delivery detection → invoice → performance report → auto-archive
- LLM cost per deal documented + within budget (target: <$10/deal end-to-end)
- All audit Tier 1 + Tier 2 fixes implemented + tested
- Documentation up to date (every workflow doc reflects current behaviour)

M17 (production hardening) is NOT v0.1; it's the bridge to v2.
