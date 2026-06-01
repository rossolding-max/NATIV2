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
- Anthropic stays at `app/agents/llm_client.py` (M2 location) — M3 explicitly does NOT relocate it to `app/vendors/`, to avoid M2 test churn for no behavioural change.
- `app/vendors/_base.py` — `BaseVendorClient` (shared Sentry breadcrumb + structlog + error mapping).
- `app/vendors/_http_client.py` — shared `httpx.AsyncClient` singleton.
- `app/vendors/_retry.py` — tenacity-based async retry (5xx + 429 honouring `Retry-After`).
- `app/vendors/_rate_limiter.py` — Redis DB 2 token bucket (Lua-atomic).
- `app/vendors/_webhook_signing.py` — HMAC-SHA256 verifier (Smartlead bare hex + Meta `sha256=` prefix).
- `app/vendors/_oauth_state.py` — CSRF state + PKCE storage in Redis DB 2 + authorize-URL builder.
- `app/vendors/smartlead.py` — campaigns / leads / sequences / webhook signature validation.
- `app/vendors/exa.py` — search / findSimilar / contents endpoints.
- `app/vendors/apollo.py` — people-by-domain + filters / match / org enrich.
- `app/vendors/linkedin.py` — `LinkedInScraperClient` via RapidAPI's "Real-Time LinkedIn Scraper API"; reads profile / company-by-domain / recent-posts. Env var: `RAPIDAPI_KEY` (legacy `LINKEDIN_API_KEY` honoured during transition).
- `app/vendors/meta_graph.py` — OAuth helpers (authorize URL + exchange + refresh) + `/{ig-user-id}/media` + `/{media}/insights` + `/{ig-user-id}/stories` + webhook signature + subscription challenge. Graph API pinned to v22.0.
- `app/vendors/tiktok.py` — OAuth helpers **with PKCE** (`generate_pkce_pair`, authorize URL with `code_challenge_method=S256`, exchange with `code_verifier`) + `/v2/video/list/` + `/v2/video/query/` + `/v2/user/info/`.
- Every wrapper: rate-limit via Redis token bucket, retry-with-backoff via tenacity, respx mock support, Sentry breadcrumb on every call.
- OAuth FastAPI callback routes are NOT in M3 — they land in M5 (talent onboarding); M3 ships the building blocks.

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
- `app/api/agencies.py` — 11 REST endpoints under `/api/v1/agencies` implementing the 9-step setup. Same surface drives the CLI wizard.
- `app/services/agency_setup.py` — state-machine helper + JSON-Schema validator (`schemas/agency_profile.schema.json`) + activation cross-field checks (DNS verified + warmup complete).
- `app/services/dns_validation.py` — direct dnspython lookups for SPF/DKIM/DMARC. **Smartlead does NOT expose a DNS API**, so M4 verifies propagation by querying TXT records directly. Default DKIM selector is `smartlead`; agencies may override.
- `app/services/branding.py` — presigned-PUT URL generator + MIME/size guards (image/png|jpeg|svg+xml, max 100 MB).
- `app/services/invoice_template.py` — starter Markdown template + GAP-07 server-side `template_version` bump on material-field changes + `next_invoice_number` (atomic counter via `SELECT ... FOR UPDATE`; consumed by M14).
- `app/services/agency_warmup.py` — Celery task `poll_mailbox_warmup_status` running hourly via Beat. Polls Smartlead's `GET /email-accounts/{id}/`, translates the warmup status, persists into `sending_mailboxes[0].warmup_status`, and auto-flips `agency_profile.status` to `active` when warmup completes AND the rest of the data is schema-valid.
- `app/utils/s3.py` — boto3 client + presigned PUT/GET URL helpers (fills in the M0 placeholder).
- `app/vendors/smartlead.py` — extended with 4 verified email-account endpoints (`create_email_account`, `get_email_account`, `update_warmup_settings`, `get_warmup_stats`).
- `app/repositories/agency_profile.py` — singleton-aware: `get_singleton`, `create_singleton` (refuses duplicates), `patch_data` (deep-merge into JSONB), `set_status`.
- `app/cli/phase0_setup.py` — interactive Typer wizard calling the REST surface; supports `--auto`, `--skip-warmup`, `--logo <path>`, `--api-base-url`.
- `app/cli/main.py` — `nativ test phase 0` wired to the wizard.
- `app/main.py` — lifespan binds `app.state.agency_id` + `agent_id` from the singleton row (was no-op at M0).

**Acceptance:** real agency setup completed via REST (or the CLI wizard); `agency_profile` row in Postgres with `status == "active"`; branding + invoice template + commission defaults populated; mailbox warmed via Smartlead.

**Skip notes:** Phase 0 cannot be skipped — it's the prerequisite to everything.

**Interdependency checks:**
- DNS records SPF/DKIM/DMARC verified directly via dnspython before transitioning to `awaiting_dns`.
- `branding` block populated with at minimum `primary_color` + `text_color` (logo optional but recommended).
- `invoice_template.invoice_number_sequence` initialised to 1; `template_version` seeded at first write.
- `default_commission_rate` + `default_commission_model` set before activation.
- Mailbox warmup polled hourly; `status` auto-flips `warming_up → active` when complete.

**Deferred from M4 (carried forward):**
- Full `Idempotency-Key` backing store (M4 logs a warning when missing; full key+response replay safety lands when M5+ first needs it).
- Live Smartlead-path confirmation against a real key (best-effort URLs ship in M4 with respx-mocked tests; first agency setup confirms).

---

## M5 — Phase 1 (Talent Onboarding)

**Inputs:** M4.

**Outputs (shipped):**
- `app/api/talents.py`: 13 REST endpoints implementing all 10 onboarding steps (per `docs/onboarding_workflow.md`).
- `app/api/webhooks/oauth_callbacks.py`: live `/api/v1/webhooks/{meta,tiktok}/oauth_callback` routes (Commit 1).
- `app/agents/tools/get_context_artefact.py`: pypdf + python-docx parser plus Claude-vision base64 image inlining (Commit 1).
- `app/models/sqla/talent_vault.py` + `alembic/versions/0004_talent_vault.py`: per-talent + per-platform OAuth-token store with column-level pgcrypto via `EncryptedString` (Commit 1).
- `app/services/talent_onboarding.py`: state machine (`onboarding → active → archived`) + `validate_data_against_schema` + `check_ready_for_activation` cross-field guard.
- `app/services/talent_seed.py` (Step 1): country-aware timezone + disclosure defaulting.
- `app/services/platform_oauth.py` (Step 2): **Meta + TikTok** flows live; PKCE for TikTok; tokens persisted via the callback route into `talent_vault`. YouTube + Twitch + LinkedIn-OAuth + Pinterest + Snap **deferred**.
- `app/services/media_pack_extraction.py` (Step 3): pre-parse via `get_context_artefact` + optional LLM extraction (opt-in `run_llm_extraction`).
- `app/services/questionnaire.py` (Step 5): rule-table-based adaptive questionnaire over `field_path` notation; LLM-driven branching deferred.
- `app/services/brand_history_enrichment.py` (Step 6): exact-match → Exa+LLM stub → unknown.
- `app/services/similar_talent.py` (Step 7): manual seed + `build_suggestion_prompt`; LLM call lands with the M7 brand-discovery loop.
- `app/services/contract_template_setup.py` (Step 7.5): GAP-08 version bump + 3 inline starter templates (management / talent-agency / brand-paid-promotion).
- `app/services/talent_background_research.py` (Step 9): Celery task `kick_off_brand_discovery` fired on `/activate`; writes a stub `data/brand_candidates/current/{talent_id}.json`. The 16-search Exa + Claude loop lands at M7.
- `app/cli/phase1_onboarding.py` + `nativ test phase 1`: interactive Typer wizard with `--auto`, `--skip-oauth`, `--skip-activate` flags.
- Tests: ~50 new (10-step happy path against testcontainers + respx-mocked Meta/TikTok; OAuth callback flow; talent-repo CRUD; GAP-08 version bump; CLI wizard e2e).

**Acceptance:** real talent onboarded; ≥1 platform connected with scope-validated tokens; `contract_template` ready for downstream contract pack generation.

**Skip notes:** individual onboarding steps can be skipped (deferred to "complete later" backlog); downstream features degrade gracefully if e.g. `working_terms.default_usage_rights` is missing.

**Interdependency checks:**
- `talent.platforms[].api_credentials.access_token_ref` populated + decryptable + scope-validated
- `talent.commission_override` either populated or explicitly defaulted to agency defaults
- `talent.contract_template` validates against schema; dry-run compose succeeds
- `talent.billing_entity.legal_name` set (required for invoicing)

---

## M6 — Phase 1.5 (Brand Deals capture)

**Inputs:** M5.

**Outputs (shipped):**
- `app/api/brand_deals.py`: 6 endpoints — `POST /talents/{id}/brand-deals` (create + auto-link to `talent.data.previous_brands[]`), `GET /talents/{id}/brand-deals?outcome=…`, `GET /brand-deals/{deal_id}`, `PATCH /brand-deals/{deal_id}` (deep-merge JSONB + re-validate KPIs), `POST /brand-deals/{deal_id}/outcome`, `DELETE /brand-deals/{deal_id}` (soft).
- `app/services/kpi_validation.py`: honesty-floor enforcement — every populated `kpiMetric` must carry `value` + `source` + `as_of`; suspicious-value flagging (engagement_rate_pct > 100, > 30% unusually high, future as_of) is non-blocking.
- `app/services/brand_deal_service.py`: orchestration — `create_deal` (resolves industry via M5's `resolve_industry`, creates `brand` row on first sight, derives `deal_id` slug, auto-links to `previous_brands[]`); `patch_deal` (mirrors scalar columns to indexed slots); `set_outcome`; `memo_kpi_pattern` skeleton (`memo_type="brand_deal_kpi_pattern"` + `scope="industry_pattern"` so M7 retrieval has data).
- `app/repositories/brand_deal.py`: `find_by_talent`, `find_by_outcome`, `patch_deal_data`, `set_scalar_columns`, `set_outcome_column`.
- Ingestion path 2 (questionnaire-guided / REST-driven) ships fully. Paths 1 (media-pack extraction → brand_deal) and 3 (platform-API nightly auto-pull) explicitly deferred per the M5.1 product call (agent is source of truth) and to M7/M9 respectively.
- Tests: ~50 new (17 KPI honesty floor + 10 service unit + 5 repo integration + 11 REST integration + e2e happy path).

**Acceptance:** real talent's past deals captured via REST; KPI honesty floor enforced on every write; auto-link to `talent.data.previous_brands[]` keeps the index in sync.

**Skip notes:** if skipped, M11 prep pack lacks comparable case studies (omits "Recent work" slide); M15 performance report lacks `vs_talent_historical` benchmark (omitted with note).

**Interdependency checks:**
- Every populated KPI has `source` enum + `as_of` date
- `outcome` enum populated per deal
- `main_brand_contact_id` references valid `brand_contact` rows where applicable

---

## M7 — Phase 2 (Brand Discovery)

**Inputs:** M6 + M3.

**Outputs (shipped — all 16 searches after M7.1):**
- `app/services/discovery/` package — all 16 searches from `docs/brand_discovery.md`. M7 shipped the Core 8 (1, 3, 5, 6, 7, 9, 10, 15); M7.1 added the remaining 8 (2, 4, 8, 11, 12, 13, 14, 16). Search 16 wraps the existing `~/.claude/skills/last30days/` skill via subprocess and is gated behind `settings.enable_last30days_discovery` (off by default — needs OpenAI + xAI keys).
- `app/services/discovery/qualification.py` — signal-based 0-1 score; signals: active_creator_program (+0.30), macro/premium tier (+0.20), established_company (+0.10), recent_funding (+0.10), follower-count boost/penalty, b2b vertical (-0.20), micro/nano (-0.15). Tier: qualified ≥0.60, speculative 0.30-0.60, unqualified <0.30 (default threshold 0.30; per-talent override deferred).
- `app/services/discovery/policy_filter.py` — partitions into kept + blocked. Blocks: `blocked_industries`, active `exclusivities`, `do_not_recontact` brand_ids. Warns: sensitive industries not in `preferred_industries`.
- `app/services/discovery/orchestrator.py` — runs enabled searches, merges sources by `brand_id`, scores (cap-summed weights), tiers (re-engage tag wins over score), qualifies, filters, returns `DiscoveryRunResult`.
- `app/services/discovery/snapshot.py` — atomic JSON snapshot writer (current + immutable per-run) that preserves agent workflow-state across runs (status, assigned_to, user_notes, pitch_history, legal_entity_override, first_surfaced_at).
- `app/services/talent_background_research.py` — M5 stub body replaced; the Celery task now runs the orchestrator, upserts `brand_candidate` rows, writes the JSON snapshot. Same task name + signature.
- `app/repositories/brand_candidate.py` — `find_by_talent` / `find_by_tier` / `upsert_run_batch` (preserves workflow-state on update) / `patch_workflow_state`.
- `app/api/brand_candidates.py` — 4 REST endpoints: GET list (with `?tier=`), GET by id, PATCH workflow, POST manual rerun (202 + enqueue).
- 101 unit tests across all 16 deterministic + LLM-driven searches, qualification, policy filter, orchestrator, Search 15 (Exa+LLM mocked), Search 13 (Anthropic mocked), Search 16 (subprocess mocked) + 10 integration tests covering repo workflow-state preservation and REST surface.

**Acceptance:** discovery run for real talent produces ranked candidates as `brand_candidate` rows AND `data/brand_candidates/current/{talent_id}.json`; workflow-state survives reruns; honesty floor enforced (no unqualified candidates surface).

**Skip notes:** if skipped, agent manually creates `brand_candidate` rows on-demand when starting outreach; downstream Phase 4.8 detection degrades if `brand.social_handles` absent for that brand.

**Interdependency checks:**
- `brand_industry_map.brands[].social_handles` populated for top-50 active brands (refresh weekly via cron)
- `brand_candidate.qualification.score` >= 0.30 for all `tier: primary` candidates
- Active exclusivities correctly filter brands

---

## M7.2 — Phase 2 (Search 17 — paid social ad signal)

**Inputs:** M7.1b + 2 new vendor wrappers (Meta Ad Library + TikTok Creative Center).

**Outputs (planned — not yet shipped):**
- `app/vendors/meta_ads.py` (NEW) — `MetaAdsClient` wrapping the public Meta Ad Library REST API. Endpoints: `search_ads(search_terms, country, ad_active_status, ad_type)` + `get_advertiser_pages(brand_name)`. Auth via Meta app token (read-only public scope). Rate limits per Meta docs (200/hr free tier).
- `app/vendors/tiktok_creative_center.py` (NEW) — v1 = HTTP scraper for the public Creative Center page (no formal API in v1; TikTok Marketing API access waitlisted). Conservative rate-limit (1 req/3s); HTML parsing via BeautifulSoup; fallback to a cached static seed when the page structure shifts. Replaceable with the TikTok Marketing API in v2 with no caller change.
- `app/services/discovery/search_17_paid_social_signal.py` (NEW) — per-industry query fan-out across Meta + TikTok; LLM (Haiku) brand-name normalisation against `brand_industry_map.json`; merge by canonical brand; emit candidates with `paid_social_active` (single-platform, weight 0.20) or `paid_social_active_multi` (multi-platform, weight 0.30) source tag. Same writeback pattern as Searches 15 + 16.
- `app/services/discovery/catalog.py` — `SEARCH_CATALOG` extended with `search_17_paid_social_signal` entry (`requires_external_skill=False`, `requires_llm=True`).
- `app/services/discovery/orchestrator.py` — dispatch wiring for Search 17.
- Settings: `enable_search_17_paid_social: bool = False` (off by default until smoke-tested on one talent in production), `meta_ads_api_token: SecretStr`, `meta_ads_default_countries: list[str] = ["US", "UK", "AU"]`, `paid_social_min_active_ads: int = 5`.
- Cassette-based unit tests (Meta Ad Library + TikTok Creative Center responses recorded once + replayed) + integration test against the orchestrator showing Search 17 candidates surface with the right weight + source tag.

**v0.1 acceptance:** discovery run for a real talent surfaces brands actively running >= 5 paid ads in the last 30 days on Meta and/or TikTok; multi-platform brands get the higher weight; brand names normalised against `brand_industry_map.json`; new brands writeback-classified with LLM.

**v0.2 (deferred per V2-DISCOVERY-02):** swap the count-based heuristic for real estimated-spend $ values via Pathmatics / SensorTower / AdBeat — `app/vendors/pathmatics.py` etc. Filter threshold becomes `estimated_monthly_paid_social_spend_usd >= 50_000` (configurable per agency). API costs ~$1k+/mo so this is a v0.2 decision once agency volume justifies the spend.

**Skip notes:** if skipped, discovery misses brands with high commercial intent on paid social — still captured noisily via Search 15 (recent funding) + Search 16 (organic momentum) but the paid-spend signal is missing.

**Interdependency checks:**
- Meta Ad Library token configured + healthy (token rotation reminder cron — separate concern).
- TikTok Creative Center scraper resilient to UI changes (selectors externalised to config; failure surfaces as warning, not crash).
- LLM brand-name normalisation against `brand_industry_map.json` adds new brands without polluting existing entries.

---

## M7.3 — Phase 2 (Brand discovery comprehensiveness overhaul)

**Inputs:** M7 + M7.1 (M7.2 orthogonal). Triggered by Kevin Cooney live test: 47 candidates, UK-only retailers leaking through, net-new Exa brands gated behind `pending_writeback`.

**Outputs (shipped):**
- `app/services/discovery/_geographic_filter.py` (NEW) — shared `extract_talent_countries()` + `brand_passes_geo()` + `filter_sources_by_geo()`. Soft-floor filter applied post-merge so a brand caught by multiple searches gets a single coherent geo decision. Talent geography chain: audience top countries → location.country → bypass when both missing.
- `app/utils/taxonomies.py` — `get_sub_industries(industry_id) -> list[str]` helper backed by a pre-computed parent→children index built at load time.
- `app/services/discovery/_models.py` — `QualifiedCandidate.tier` Literal extended with `"emerging"`.
- `app/services/discovery/qualification.py` — net-new brands with an Exa-search source tag (`recently_funded` or `established_exa_discovery`) + LLM confidence ≥ 0.70 → `tier="speculative"`, `score=0.30`, signal `emerging_exa_discovery`. Backward-compat preserved for brands without seed entry AND without Exa tag (still `unqualified`).
- `app/services/discovery/search_5_7_industry_tiers.py` + `search_8_parent_sibling_niche.py` — sub-industry walk: each target industry expands to its children via `get_sub_industries`. Weight decay `0.8x` for sub-industry hits.
- `app/services/discovery/search_15_exa_newly_funded.py` — query variations bumped 2 → 7 per industry, talent country embedded, weight bumped `0.10-0.15` → `0.20-0.30` scaled by LLM confidence so net-new brands clear the qualification noise floor.
- `app/services/discovery/search_18_established_brands.py` (NEW) — mirror of Search 15 for established brands. 6 query variations per industry covering `top/best/D2C/creator program/established/to watch` angles. `search_tag="established_exa_discovery"`.
- `app/services/discovery/orchestrator.py` — dispatches Search 18 alongside Search 15, threads talent country through both, caps via `settings.discovery_max_industries_per_run=5`, applies geo filter post-merge, assigns `tier="emerging"` for Exa-only candidates that pass qualification.
- `app/services/discovery/catalog.py` — registered 18th search entry.
- `app/api/brand_candidates.py` — `?qualification=qualified,speculative,unqualified,all` query param on the list endpoint (default `qualified,speculative` preserves v0.1 behaviour). Tier pattern extended to include `emerging`.
- `app/config.py` — `discovery_max_industries_per_run: int = 5`.
- 29 new unit tests (geo filter permutations, sub-industry walk + decay, Search 15 query expansion, Search 18 full pipeline, qualification emerging tier, taxonomies sub-industry lookup, Kevin E2E) + 4 new integration tests for the `?qualification=` filter + updated catalog count test (17 → 18).
- `docs/brand_discovery.md` — Search 18 spec, geo filter section, sub-industry expansion section, emerging tier section.

**Acceptance:** Kevin-shaped synthetic E2E (real taxonomies + real brand_industry_map + mocked Exa/Claude) surfaces ≥ 50 candidates (v0.1 baseline 47), zero UK-only retailers, ≥ 1 `tier="emerging"` candidate. Live re-run for Kevin produces 150+ candidates (mocked-Exa quota permitting).

**Skip notes:** N/A — overhaul of an already-shipped milestone. If reverted, the v0.1 Kevin run regresses to the 47-candidate UK-leaking baseline.

**Interdependency checks:**
- Geo filter does NOT regress talent runs where audience + location are both empty (filter is bypassed).
- Sub-industry expansion does NOT regress single-leaf-industry talent runs (no children → no extra hits).
- `?qualification=` default preserves v0.1 REST behaviour for any UI not yet aware of the toggle.

**Deferred to v0.2:** large-scale seed-map writeback automation (the script that promotes high-confidence Search 15/18 discoveries into `brand_industry_map.json` quarterly), brand-size tiering, sub-niche → sub-industry affinity overrides.

---

## M7.4 — Phase 2 (Industry breadth + auto-grown seed map + brand canonicalization)

**Inputs:** M7.3. Triggered by the live Kevin run: 142 candidates capped at 5 industries; false net-new "Ford Motor Company"/"General Motors" inflating emerging tier; no feedback loop from discovered brands into the seed map.

**Outputs (shipped):**
- `app/services/discovery/_brand_normalizer.py` (NEW) — `normalize_brand_name()` strips leading "the" + trailing corporate suffixes (longest-first); `find_canonical_seed_entry()` matches against seed name + aliases post-normalize.
- `app/services/discovery/_seed_map_loader.py` (NEW) — `load_merged_brand_industry_map()` loads curated + auto-grown discovered files; dedupes via the brand normalizer; curated wins on conflict.
- `app/services/discovery/_industry_expansion.py` (NEW) — `expand_past_deal_industries_bidirectionally()` walks past-deal sub-industries UP to parent + ACROSS to all siblings.
- `app/services/discovery/_industry_softener.py` (NEW) — one Haiku call per run; given talent context + already-chosen industries + the full industries.json catalogue, returns up to 20 additional industry_ids filtered against the taxonomy whitelist.
- `app/services/discovery/_discovered_writer.py` (NEW) — atomic `tempfile` → `os.replace` appender for `brand_industry_map_discovered.json`. Dedupes against curated + discovered before append.
- `app/services/discovery/orchestrator.py` — pre-step `_compute_industry_expansions` runs at the top of `run_discovery`; combined extras feed Search 5 (as primary tier extras) + the Exa seed for S15/S18; `[: discovery_max_industries_per_run]` slicing removed; warn at >50 industries.
- `app/services/discovery/search_5_7_industry_tiers.py` — `extra_target_industries` parameter; extras only fire on the primary tier (no double-emit at lower tiers).
- `app/services/discovery/search_15_exa_newly_funded.py` + `search_18_established_brands.py` — replace inline `_slugify` with shared `slugify_brand_name`; pre-canonicalize via `find_canonical_seed_entry` so Exa hits for "Ford Motor Company" / "General Motors" emit onto the canonical "Ford" / "GM" brand_ids instead of as net-new emerging.
- `app/services/discovery/snapshot.py::_candidate_to_dict` — adds derived top-level `primary_source_search` field (highest-weight source's `search_tag`, ties broken alphabetically).
- `app/services/talent_background_research.py` — after `run_discovery`, calls `append_discovered_brands()` so net-new brands persist into `brand_industry_map_discovered.json` for future runs.
- `app/utils/slugify.py` — adds lenient `slugify_brand_name()` (returns `"unknown"` on bad input) for Exa/LLM-extracted name canonicalization.
- `app/config.py` — drops `discovery_max_industries_per_run`; adds `discovery_industry_softener_enabled: bool = True`.
- `data/brand_industry_map_discovered.json` (NEW) — empty starter file that grows with every run.
- 39 new unit tests: 13 normalizer + 4 loader + 8 expansion + 5 softener + 3 canonicalization + 6 writeback. 728 total unit tests pass.
- `docs/brand_discovery.md` — M7.4 sections: industry softener, bidirectional walk, brand canonicalization, auto-grown discovered seed map, per-candidate source provenance.

**Acceptance (unit):** Kevin synthetic E2E surfaces ≥ 50 candidates, every candidate has `primary_source_search` populated. **Acceptance (live, pending smoke run):** Kevin live re-run produces > 250 candidates (vs M7.3 baseline 142); zero "Ford Motor Company" / "General Motors" / "Kroger" net-new entries (canonicalised); `brand_industry_map_discovered.json` grows by 80+ entries that subsequent runs for other talents will see.

**Skip notes:** N/A — overhaul of an already-shipped milestone. Reverting regresses to the 142-candidate M7.3 baseline.

**Interdependency checks:**
- LLM softener stays gated on `discovery_industry_softener_enabled` so test runs don't accidentally hit the live API.
- Bidirectional walk fires only for past-deal industries — talents with no historical deals get the same behavior as M7.3.
- `?qualification=` REST default still preserves v0.1 behaviour.
- Discovered seed map appended atomically; concurrent Celery workers race is accepted v1 trade-off.

**Deferred to v0.2:** brand-name canonicalization across runs (a brand named "Kroger" in run 1 and "The Kroger Co" in run 2 still lands as two discovered entries — per-run normalizer handles within-run only); discovered → curated promotion UI (promote a brand surfaced N+ times to curated); cost budget alarm; embedding-based brand similarity.

---

## M7.7 — Phase 2 (v2 architecture refactor — 4 phases + human-in-the-loop)

**Inputs:** M7.6. Triggered by user wanting (a) Exa-based brand discovery instead of seed-map-bounded walks, (b) gap-free coverage between emerging + established, (c) human-in-the-loop industry review before expensive Exa fan-out, (d) one-off massive build + monthly maintenance cost shape.

**Outputs (shipped):**
- 4-phase architecture:
  - **Phase 1** (`phase_1_industry_compilation.py`): composes affinity walk + bidirectional walk + softener + new `_industry_from_audience.py` / `_industry_from_life_stage.py` / `_industry_from_exclusivity.py` (extracts S9/S11/S12 industry-derivation logic). Returns `list[IndustryProposal]` each with rationale + source. Dedup priority: affinity > past-brand > similar-talent > bidirectional walk > audience > life-stage > exclusivity > softener > manual.
  - **Phase 1.5** (`industry_review` SQLA model + REST endpoints): human-in-the-loop review queue. Three endpoints under `/talents/{id}/industry-review`: GET (fetch pending), PATCH (add/remove industries), POST `.../approve` (mark approved + enqueue Phase 2). One pending review per (talent, agency); supersedes prior pending.
  - **Phase 2** (`phase_2_brand_universe_build.py`): per-industry Exa fan-out across 3 categories — emerging / **growth (NEW)** / established. NO cap on industries. Per-query Exa+Claude with M7.5 provenance. Three search tags: `exa_emerging`, `exa_growth`, `exa_established`. Phase 2 absorbs S5-S12, S14, S18.
  - **Phase 3** (`phase_3_talent_specific.py`): wraps S1, S2, Exa-S3 (`_competitor_search_exa.py`), Exa-S4, S13 standalone (`_values_search.py`, opt-in).
  - **Phase 4** (`phase_4_signal_overlay.py`): S15-residual rewritten as industry-AGNOSTIC global trending funded sweep + S16 (gated) + S17 (gated).
- **First-class brand metadata**: `QualifiedCandidate` gains `sub_industry_id` + `brand_category`. Snapshot, discovered seed map, and Brand DB stub all carry them.
- **REST**: `TriggerDiscoveryBody.mode: Literal["full_build", "maintenance"] = "maintenance"`. `full_build` runs Phase 1 inline + returns review URL pointer; operator approves to trigger Phase 2 Celery task (`kick_off_phase_2_brand_universe`).
- **Monthly Phase 4 cron** (`discovery_phase_4_monthly.py` + Celery beat): walks active talents (deal in last 90d OR discovery in last 60d) and enqueues maintenance-mode runs.
- **Config**: `discovery_v2_enabled` (default True; rollback to M7.6 via False), `discovery_growth_enabled` (default True), `discovery_phase_4_monthly_enabled` (default True), `discovery_values_search_default_themes` (default []).
- 47 new unit tests + 8 integration tests for review queue + REST surface. 783+ total unit tests pass.

**Acceptance (unit):** all phases produce expected outputs against mocked Exa+Claude. **Acceptance (live, pending Kevin smoke):** full_build → operator approves all 80+ industries → Phase 2 produces > 2000 candidates with 3 distinct `brand_category` tags + `sub_industry_id` set on most rows; discovered seed map grows by 1500+; subsequent maintenance run completes in < 2 min for < $5.

**Skip notes:** Rollback via `discovery_v2_enabled=False` reverts to M7.6 legacy path. Deprecated search modules kept on disk through M7.7; M7.8 deletes them.

**Interdependency checks:**
- `industry_review` table migration (alembic 0005) runs before any v2 REST traffic.
- `discovery_v2_enabled=True` requires the Phase 2 Celery task (`kick_off_phase_2_brand_universe`) to be registered (`app.services.talent_background_research`).
- Geography embedded in every Phase 2 + Phase 3 + Phase 4 Exa query template so UK-only brands don't surface in the first place; M7.3 post-merge geo filter still runs as defence in depth.

**Deferred to v0.2:** per-industry-vertical custom prompts; Phase 1 → Phase 2 incremental refresh; cross-talent discovered-brand promotion to curated; S16/S17 ungating (need vendor tokens); auto-expire pending reviews (14-day TTL); industry-review UI (REST surface ships M7.7; UI in a later milestone); deprecated search module deletion (kept for rollback through M7.7).

---

## M8 — Phase 3a (Contact CRM)

**Inputs:** M7.

**Outputs (shipped — full 9-step pipeline):**
- `app/services/contact_enrichment/` package — Steps 2 (Apollo search), 3 (LinkedIn enrich), 4 (Exa + Claude web-search fallback), 5 (strict email honesty floor), 6 (Claude `decision_role` classifier — single batched call per run), 8 (dedupe + merge), qualification + policy filter, orchestrator.
- `app/services/contact_enrichment/snapshot.py` — atomic dual-write JSON snapshot (`data/brand_contacts/current/{brand_id}.json` + immutable `data/brand_contacts/runs/{brand_id}/{run_id}.json`). Preserves workflow-state fields across runs.
- `app/services/contact_enrichment_task.py` — Celery task `kick_off_contact_enrichment(brand_id, agency_id, talent_id?, target_titles?)` fired by the new REST trigger.
- `app/repositories/brand_contact.py` extensions: `find_by_brand`, `find_pitchable_for_talent`, `upsert_run_batch` (workflow-state preserved), `patch_workflow_state`, `set_scalar_columns`.
- `app/api/brand_contacts.py` — five REST endpoints (list per brand, list pitchable per talent, get by id, patch workflow state, trigger enrichment run).
- 63 unit tests across 9 modules; 5 integration tests for the repo (workflow-state preservation); 11 integration tests for the REST surface (happy + 404 paths + Celery enqueue assertions).

**Acceptance:** contacts surfaced on real brand via `POST /brand-contact-enrichment/run`; verified email rate > 70%; `decision_role` populated with rationale; manual trigger only in v0.1 (auto-fire from M7 deferred to M8.1).

**Skip notes:** if skipped, agent manually enters contact details when creating enrollment; `decision_role` defaulted to `unknown`.

**Interdependency checks:**
- Every contact has `decision_role` + `decision_role_rationale`
- `qualification` signals + tier populated per contact
- `do_not_contact` + `opt_out_at` honoured across talents (shared roster contact pool)

---

## M9 — Phase 3b (Outreach)

**Inputs:** M8.

**Outputs (shipped — full v0.1 chain):**
- `app/services/outreach/` package — template selector, angle filter (13 high-signal triggers; rest fail-soft), per-step LLM generator (Opus step 1, Haiku steps 2+; ≤3 validation retries), policy filter (DNC + active-enrollment + 14-day cooldown), loopback writers (`brand_contact.pitch_history[]` + `brand_deal.last_re_engagement_pitch_date`), Smartlead push, reply classifier (Haiku, 7 outcomes), deal creator (GAP-06 bidirectional FK in one transaction), orchestrator, atomic JSON snapshot writer.
- 3 default templates in `data/pitch_templates/` (buyer-direct-pitch 4 steps, influencer-warm-intro 3 steps, champion-activation 2 steps) + 42-angle seed (`data/pitch_angles.json`) + `scripts/seed_pitch_{angles,templates}.py` idempotent importers.
- `app/services/outreach_reply_handler.py` — webhook reply pipeline (classify → side-effect routing).
- `app/services/outreach_generation_task.py` — Celery task wrapping the orchestrator.
- `app/services/enrollment_state_sync.py` — 5-min Celery beat task reconciling Smartlead campaign status.
- `app/api/enrollments.py` — 7 REST endpoints across 3 routers (list-by-talent, list-by-brand, get, patch, approve [Step-1 gate; pushes Smartlead inline], outreach-generation/run [Celery enqueue], kill).
- `app/api/webhooks/smartlead.py` — 2 webhook handlers with HMAC-SHA256 verification + Redis 24h-TTL dedupe on `(campaign_id, lead_id, event_type, occurred_at)`. Bounce kills enrollment + marks contact email bounced; unsubscribe sets contact DNC + cross-roster kill.
- **GAP-06 audit fix:** `interested` reply creates Phase-4 Deal in `lead`/`new_lead` (or `initial_call_scheduled` if `asked_for_meeting`) with `originating_enrollment_id` + `originating_decision_role_at_pitch` snapshot, and bidirectionally UPDATEs `pitch_enrollment.created_deal_id` — both ops in one DB transaction.
- 59 unit tests (template + angle + generator + policy + classifier + deal-creator + reply-handler + smartlead-push + loopback + orchestrator) + 17 integration tests (5 repo + 11 REST + 6 webhook including reply→deal bidirectional FK round-trip).

**Acceptance:** real outreach campaign sent; replies received; classifier accuracy >85% on labelled test set; `interested` reply triggers deal creation with full bidirectional FK setup. Manual approval gate on Step 1 enforced.

**Skip notes:** if skipped, agent manually creates Phase 4 deals in LEAD; `originating_enrollment_id` null on those deals.

**Interdependency checks:**
- Every sent email has full `pitch_enrollment.steps[].generation_meta` provenance (angles_used, personalization_fields_used, prompt_hash)
- Reply classification populates `outcomeClassification.extracted_signals` (asked_for_meeting / pricing / etc.)
- `brand_contact.pitchHistoryEntry.enrollment_id` populated as denormalised index

---

## M10 — Phase 4 (Deal Lifecycle skeleton)

**Inputs:** M9.

**Outputs (shipped):**
- `app/services/deal_lifecycle/` package — `transitions.py` (static TRANSITIONS table for 28 substages + TERMINAL_SUBSTAGES + AUTO_ADVANCE map), `state_machine.transition()` (returns 1- or 2-step chain; raises `BusinessRuleError` with allowed-targets in `detail`), `loss_reasons.validate_reason()` + `lost_at_stage_for()`, `orchestrator.apply_transition()` + `orchestrator.record_loss()` (mutates `deal.stage` + `deal.substage` + `is_terminal` + `is_won` + appends `data.stage_history[]`).
- `app/repositories/deal.py` extensions — `find_by_talent` / `find_by_brand` / `find_by_stage` / `find_due_for_action` finders, pipeline scanners `find_ready_for_prep_pack` (1-hour debounce on `data.prep_pack_enqueued_at`) + `find_ready_for_archive` (3-gate close check), `insert_manual_deal` (opening `stage_history` entry), `patch_workflow_state` with guards (refuses direct `stage` / `substage` / `data.loss` / `data.stage_history` writes).
- `app/api/deals.py` — 9 endpoints across talent-scoped + brand-scoped + top-level routers (`GET .../deals`, `GET /deals/due-for-action`, `GET /deals/{id}`, `GET /deals/{id}/stage-history`, `POST /deals`, `PATCH /deals/{id}`, `POST /deals/{id}/transition`, `POST /deals/{id}/loss`). Transition endpoint returns the full chain (so the UI shows both steps when auto-advance fires).
- 2 Celery beat tasks: `app/services/deal_phase_4_5_auto_fire_task.phase_4_5_auto_fire` (5-min; enqueues `app.tasks.pack_generation.generate_pack(pack_type="discovery_prep", ...)` for deals at `initial_call_scheduled` + no prep pack) and `app/services/deal_auto_archive_task.auto_archive_trigger_check` (15-min; archives deals once all 3 close gates pass).
- Auto-cross-stage transitions: agent transition to `qualified` chains to `proposal_drafting`; `terms_agreed` chains to `contract_drafting`; `contract_executed` chains to `pre_production`. Each auto-advance writes its own `stage_history[]` entry with `by_agent_id="system"`.
- Audit fixes: Tier-1 G2 (`data.delivery.campaign_hashtags[]` editable via PATCH); Tier-2 R4 ("least-progressed wins" documented in workflow doc; ships in M14 alongside the per-deliverable kanban surface).

**Tests:** 30 unit (state machine + transitions table sanity + loss reasons + orchestrator audit + auto-advance) + 10 unit task tests (`process_ready_deals` + `process_ready_archives`) + 20 integration REST tests (`tests/integration/api/test_deals_crud.py`) + 12 integration repository tests (`tests/integration/test_deal_repository.py`). Total: 605 unit + 32 M10 integration.

**Acceptance (met):** deals progress through LEAD → PROPOSAL → CONTRACT → DELIVERY → CLOSE manually via API; invalid transitions rejected with allowed-targets in error detail; lost deals tagged with structured reasons via `POST /deals/{id}/loss`; auto-advance chains visible in REST response + stage_history.

**Skip notes:** N/A (Phase 4 is required for any pack work).

**Deferred to M10.1+ / later milestones:**
- Discovery / Proposal / Contract / Performance-Report pack generators → M11–M15.
- Performance detection + KPI capture → M14 (writes `posting_schedule[]` + `interim_kpi_snapshots[]`).
- Brand_deal closing-row write on archive → M16.
- Per-deliverable kanban UI + "least-progressed wins" computation surface → M14.
- Deal cloning, pipeline forecasting (`expected_value × probability(stage)`), stage SLA tracking, LLM-suggested next_action, pipeline CSV/PDF export, daily morning-summary digest → v0.2.

---

## M11 — Phase 4.5 (Discovery Prep Pack) ⭐ first AI pack

**Inputs:** M10 + M2.

**Outputs (shipped):**
- `app/agents/packs/discovery_prep.py` — 4-pass coordinator (researcher + writer-briefing + writer-agenda + writer-slides) over `claude-opus-4-7` (default; settings.discovery_prep_model override). Static bundle prefix (talent + agency + brand + deal) cached across passes 1-3 via Anthropic prompt cache.
- `app/agents/tools/exa_tools.py` (NEW) — `bind_exa_tools(agent_name, max_queries=5)` wraps the M3 ExaClient. Researcher subagent runs 3-5 queries; URLs preserved for slide sources.
- `app/services/prep_pack_persistence.py` (NEW) — atomic persist: flip prior versions' `is_latest` -> INSERT new row -> write 4 markdown artefacts (`briefing-notes.md` + `agenda.md` + `slides.md` + `speaker-notes.md`) + `v{N}.json` via filesystem helper -> mirror `prep_pack_id` to `deal.latest_prep_pack_id` + `deal.data.lead.latest_prep_pack_id` + `deal.data.lead.discovery_prep_pack_ids[]`.
- `app/agents/bundles.py` extended — wires the previously-empty `brand_contact` / `comparable_brand_deals` / `top_pitch_angles` / `agency_profile` fields from M4/M6/M8/M9 repos.
- 2 memo writes per generation: researcher writes `brand_observation` (scope `brand_relationship`); slides-pass writer writes `talent_pattern` (scope `talent_pattern`). Both bound at agent construction.
- NL feedback regeneration loop (full-pack only in v0.1; section-targeted defers to M11.1). `POST /deals/{id}/prep-pack/regenerate` body `{feedback, pre_generation_guidance?}` looks up latest version + threads `parent_version` into the dispatcher.
- Auto-fire on `substage="initial_call_scheduled"` **gated behind `settings.enable_phase_4_5_auto_fire`** (default `False` until 3-5 manual packs smoke-tested). Manual `POST /deals/{id}/prep-pack/generate` is the canonical v0.1 trigger.
- 4 REST endpoints under `/deals/{deal_id}/prep-pack`: `GET ` (latest), `GET /versions`, `POST /generate` (202), `POST /regenerate` (202).
- v0.1 deliverables: 4 markdown files on local filesystem (`data/deals/{deal_id}/discovery_prep/v{N}/`). HTML/PDF/PPTX renderer subagent + S3 migration both defer to V2-PACK-01 / M12+.

**Tests:** 22 unit (Exa tools, persistence, bundle wiring, 4-pass sequence, auto-fire gate) + 9 integration REST tests. Total: 627 unit + 9 M11 integration; M10 regressions clean (32 pass).

**Acceptance (met):** real deal at `initial_call_scheduled` can be manually triggered via `POST /generate`; the 4-pass coordinator produces structured briefing/agenda/slides JSON, persists the row, writes the 4 markdown artefacts, mirrors `deal.latest_prep_pack_id`; NL feedback regen produces v2 with `parent_version=1`; 2 memos round-trip retrievable via tags.

**Skip notes:** if skipped, agent goes into discovery call without auto-drafted pack; `deal.lead.discovery_call_notes` captured manually post-call.

**Deferred to M11.1+:**
- Section-targeted regen (`agent_section_regenerate`, `agent_per_slide_regenerate`, `target_sections[]`) — JSON schema supports the future shape.
- HTML / PDF / PPTX rendering (V2-PACK-01); renderer subagent first invoked in M12.
- Agency-branded export.
- S3/MinIO migration (currently filesystem per `pack_storage.py`).
- Cassette-based LLM integration test of the full pipeline (current coverage = unit 4-pass + REST integration).
- Langfuse per-call span emission.
- Closed-loop quality learning from agent edits.

**This is the foundational AI pack — proves the entire agent architecture for v0.1 (coordinator + skill subagents + memo store + context bundles + cost telemetry).** Subsequent packs (M12-M15) reuse the same skill subagents with different compositions; M12 (proposal pack) is where the renderer subagent first ships.

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
