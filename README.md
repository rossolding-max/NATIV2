# NATIV2 — AI Influencer Marketing Assistant

## Goal

Build an AI-powered assistant that helps an influencer (or a roster of influencers) **find, connect with, and close deals with brands** to promote their products. The assistant should automate the manual grind of brand discovery, outreach, negotiation, and deal admin — while keeping the creator in control of voice, values, and final approvals.

## Phases

| # | Phase | Status | Purpose |
|---|-------|--------|---------|
| 1 | **Talent Profile** | v0.1 spec + data shipped | Capture everything the system needs about the creator(s) — identity, audience, history, rates, similar talents. The foundation every later phase reads from. |
| 2 | **Brand Discovery & Targeting** | v0.1 spec + data shipped | For a given talent, produce a ranked list of industries to pitch and a ranked long-list of specific brands within them — with qualification filtering, sensitive-vertical warnings, and re-engagement on a monthly cron. |
| 3a | **Contact CRM** | v0.1 spec + schema shipped | For every primary-tier brand candidate, find the right named contacts (Apollo + LinkedIn API + web search) with verified emails, LinkedIn URLs, location, tenure, and a `decision_role` classification (CMO of a $50B brand is *not* the buyer for a £5k Reel — the IM Manager 2 levels down is). |
| 3b | **Outreach** | v0.1 spec + schemas + angles library shipped | AI-generated personalised email sequences per contact + decision_role, sent via Smartlead from per-talent domains, with reply detection, kill-on-reply, and full per-email analytics provenance. |
| 4 | **Deal admin** | TBD | Contracts, invoicing, usage-rights tracking, exclusivity-clock management, post-campaign reporting. |

## End-to-end data flow

```
┌────────────────────────────────────────────────────────────────────┐
│ Phase 1  TALENT PROFILE                                            │
│   docs/onboarding_workflow.md     ← how a talent gets in           │
│   schemas/talent.schema.json      ← what the data looks like       │
│   talents/{id}.json               ← per-talent file                 │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 2A  INDUSTRY RECOMMENDATION                                  │
│   docs/recommendation_algorithm.md                                 │
│     5-layer score: direct(60%)+bridge(25%)+past(5%)+pref(10%)+pol  │
│     reads: niches.json, industries.json, *_affinity.json, IAB taxo │
│     output: ranked industry list with `why[]`                      │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 2B  BRAND DISCOVERY (16 parallel searches)                   │
│   docs/brand_discovery.md                                          │
│     reads: talent profile + every data/*.json + Exa + last30days   │
│     output: data/brand_candidates/current/{talent_id}.json         │
│     schema: schemas/brand_candidates.schema.json                   │
│   monthly cron + on-profile-change + on-demand                     │
└────────────────────────────┬───────────────────────────────────────┘
                             │
        (background, continuous)
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 2C  BRAND ENRICHMENT (writeback loop)                        │
│   docs/brand_enrichment_workflow.md                                │
│     9-step pipeline: identity → domain → industry → HQ/markets →   │
│     stage → tier → creator program → financials → social followers │
│     output: data/brand_industry_map.json grows over time           │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 3a  CONTACT CRM                                              │
│   docs/contact_enrichment_workflow.md                              │
│     9-step pipeline: identify target roles → Apollo lookup →       │
│     LinkedIn API enrichment → web-search backup → email verify →   │
│     decision-role classify → placeholders → dedup → write          │
│     output: data/brand_contacts/{brand_id}.json (gitignored, PII)  │
│     schema: schemas/brand_contact.schema.json                      │
│   triggered on primary-tier brand promotion + manual + quarterly   │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 3b  OUTREACH                                                  │
│   docs/outreach_workflow.md                                         │
│     Per qualified contact + decision_role: select template →        │
│     evaluate angles (data/pitch_angles.json) → AI-generate every    │
│     step (Claude Sonnet step 1, Haiku follow-ups) → review queue →  │
│     push to Smartlead → real-time webhooks → reply classification   │
│     → kill across roster → analytics aggregation                    │
│   schemas/pitch_template + pitch_enrollment + pitch_angle           │
│   send via Smartlead from per-talent sender domains                 │
└────────────────────────────────────────────────────────────────────┘

   Cross-cutting:  docs/vendor_roadmap.md  ← external services + env vars
```

---

## Phase 1 — Talent Profile

### Output
A JSON file (`talents/*.json`) per talent, validated against `schemas/talent.schema.json`. The repo supports a **multi-talent roster** — one file per creator, or a combined roster file.

### Captured fields
- **Identity**: id, name, pronouns, age/DOB, location, timezone, languages, bio, content niches.
- **Contact**: direct email, manager/agency contact, phone (optional).
- **Billing entity**: company/legal name, country of operation, tax/VAT ID, preferred payment methods. _(Needed before any deal can be invoiced.)_
- **Platforms & handles**: per-platform handle, URL, follower count, engagement rate, avg views/likes/comments, and a **reference** to that platform's API key (e.g. `env:INSTAGRAM_TOKEN`) — never the raw secret.
- **Audience demographics**: age bands (IAB-aligned 5-year bands: 18-20, 21-24, 25-29, ..., 75+), gender split, top countries/cities, top languages, interests. Per-platform overrides supported.
- **Previous brand deals** (rich): brand name, industry, campaign date, platform, deliverables, fee (optional), usage rights granted, performance notes, brand contact.
- **Similar talent**: thin pointer (id, name, handles, previous brand collaborations). The app enriches each record by AI research and back-derives `inferred_niches` from the brand list — see `docs/recommendation_algorithm.md` § Similar-talent inversion.
- **Rate card**: per platform → per deliverable type (e.g. Instagram → Reel / Story / Feed / Carousel / Live). Supports bundles, usage rights uplift %, exclusivity uplift %, whitelisting uplift %.
- **Brand preferences & restrictions**: preferred industries, blocked industries (e.g. gambling, alcohol), active exclusivities (with end date), values/red lines.
- **Working terms**: default usage rights (organic / whitelisting / paid social), default usage duration, content turnaround time, revisions included, blackout/availability dates.
- **Press kit & assets**: link to media kit, headshots, demo reels, notable press mentions, awards.
- **Disclosure defaults**: FTC/ASA disclosure style (`#ad`, `#sponsored`, etc.).
- **Other stats**: free-form key/value bag for anything that doesn't fit (e.g. newsletter subs, podcast downloads, Discord size).

### Added beyond the original brief
The fields below were not in the original request but were added because later phases (outreach, negotiation, contracts, invoicing) will fail without them:
- Billing entity / tax info.
- Per-platform follower count, engagement rate, avg views/likes/comments (live stats — needed for media-kit-style pitches).
- Brand preferences/restrictions and active exclusivities (so the assistant doesn't pitch a conflicting brand).
- Default usage rights, turnaround, revisions (so rate-card quotes are apples-to-apples).
- Disclosure defaults (compliance).
- Press kit URL and assets (so outreach emails can attach proof).
- Free-form `other_stats` bag for anything bespoke.

### Files
- `schemas/talent.schema.json` — JSON Schema (Draft 2020-12) describing the talent profile.
- `schemas/brand_candidates.schema.json` — JSON Schema for the per-talent Brand Discovery output. Validates every file written by the orchestrator under `data/brand_candidates/` (the folder itself is gitignored — generated artifact, not source).
- `schemas/brand_contact.schema.json` — JSON Schema for per-brand contact records (Phase 3a). Validates every file under `data/brand_contacts/` (gitignored — contacts are PII and vendor data is licensed).
- `schemas/pitch_angle.schema.json` + `data/pitch_angles.json` — curated library of 37 pitch angles across 15 categories (competitive proof, similar-talent precedent, demographic match, niche fit, brand momentum, geographic alignment, mutual connection, values alignment, re-engagement, performance proof, timeliness, creative concept, insider observation, role defaults, counter-positioning). Each angle has trigger conditions, applicable decision roles + steps, strength score, example phrasing. Powers the AI generation step in Phase 3b outreach.
- `schemas/pitch_template.schema.json` — sequence templates (structure not content). Per-step intent + timing + preferred angle categories. 3 default templates ship per decision_role.
- `schemas/pitch_enrollment.schema.json` — running instance of a template for a specific (talent, contact). Full per-email provenance: which angles used, which model, full engagement event log, LLM-classified outcome. Validates files under `data/pitch_enrollments/` (gitignored).
- `scripts/analyze_outreach.py` — rolls every enrollment step into A/B-sliceable aggregates (by angle, decision_role, template, step, brand_tier, send_time, subject_pattern, sender_domain, etc.). Outputs `data/outreach_analytics/` (gitignored).
- `talents/example-talent.json` — template instance, partially filled.
- `data/niches.json` — canonical creator content-niche taxonomy (145 entries).
- `data/industries.json` — canonical brand-industry taxonomy (178 entries).
- `data/brand_industry_map.json` — seed lookup of well-known brand names → `industry_id` (290 brands, all enriched with `hq_country`, `sells_in_countries`, `company_stage`, `typical_campaign_tier`, `creator_program_presence` for Brand Discovery searches; **62% additionally carry `revenue`, 70% `headcount` bands, 62% `social_followers` per platform** with `source` provenance and `as_of_year` — honest-gaps policy: omitted when not confident). Used by the app's auto-complete and grows over time.
- `data/brand_competitors.json` — curated brand-to-brand direct-competitor graph (290 brands, 1,241 directed edges). Powers Brand Discovery Search 3/4/14 (direct + transitive competitor lookups). Captures actual competitive sets (Tesla ↔ Rivian/Polestar/Lucid) rather than just same-industry membership.
- `data/iab_audience_taxonomy_v1.1.json` — official IAB Tech Lab Audience Taxonomy v1.1 (1,558 segments), used as the audience-profile bridge between niches and industries.
- `data/niche_industry_affinity.json` — direct authored niche↔industry affinity matrix (1,246 edges across 145 niches).
- `data/niche_audience_affinity.json` — bridge leg 1: niche → IAB audience segments.
- `data/industry_audience_affinity.json` — bridge leg 2: industry → IAB audience segments.
- `scripts/build_affinity.py` — builder script with all authored data and inline validation. Single source of truth for the three affinity files; re-run to regenerate them.
- `scripts/enrich_brand_map.py` — adds the 5 metadata fields per brand to `brand_industry_map.json`. Re-runnable; honest-gaps policy (omit fields where the curated value is unknown).
- `docs/recommendation_algorithm.md` — draft spec for how the app combines all of the above into a ranked list of industries to target for a given talent. Forward-looking contract for when the app is built.
- `docs/onboarding_workflow.md` — draft spec for how a user adds a new talent: web wizard with OAuth platform connections (paste-fallback), media-pack extraction by LLM, adaptive questionnaire for gaps, hybrid similar-talent seeding (user + AI suggestions), and a background AI research pass that populates similar-talent records.
- `docs/brand_discovery.md` — draft spec for the long-list generator. **16 independent searches** runnable today (re-engagement, network expansion, affinity expansion, geo, life-stage, constraint-aware, graph, recently-funded via web search, **trending/rising brands via the [`last30days` skill](https://github.com/mvanhorn/last30days-skill) — multi-source social momentum signal across Reddit/X/TikTok/YouTube/HN/etc., run as a monthly cron**) merged with multi-source scoring. Monthly cron drives re-engagement with per-brand cool-downs. Future-versions section lists 12 more searches that need external data (Crunchbase API as a structured upgrade to Search 15, live `#ad` scraping, affiliate networks, creator marketplaces, EMV reports, etc.). Both structural enrichments (`brand_industry_map` metadata + `brand_competitors` graph) are now shipped and used by Searches 3, 4, 10, 14.
- `docs/vendor_roadmap.md` — single source of truth for external-service decisions. Confirms **Exa** as the v0.1 web-search provider (Search 15). Catalogues deferred vendors with criteria for when to add each: ScrapeCreators (Search 16 visual platforms), Owler (competitor maintenance), Modash/HypeAuditor (brand DB bulk import), Exploding Topics (pre-trend detection), Product Hunt API (day-of launches), Tribe Dynamics EMV (top-spending brands per category), SimilarWeb (audience-overlap competitors), Crunchbase (structured funding data), Apollo (Phase 3 outreach contact discovery), plus alternatives for each. Includes the env-var inventory for all current + deferred services.
- `docs/brand_enrichment_workflow.md` — draft spec for the 9-step pipeline that takes a brand from name-only to fully-populated record in `brand_industry_map.json`. Covers identity resolution, domain resolution, industry classification, HQ/markets, company stage, campaign tier, creator-program presence, revenue + headcount, social follower counts. Three triggers (seed expansion / in-flight discovery writeback / annual refresh), tool-per-step mapping, honesty-floor policy, validation gates, and a state machine. Pairs with brand_discovery.md (consumer) and vendor_roadmap.md (external services).
- `docs/contact_enrichment_workflow.md` — Phase 3a spec for the 9-step pipeline that turns a primary-tier brand candidate into a list of named contacts with verified emails, LinkedIn URLs, location, tenure, and decision-role classification. Covers target-role identification (scaled to brand size), Apollo employee lookup, LinkedIn API enrichment, web-search backup via Exa, email verification, LLM-driven decision-role classification with the simplified 5-value taxonomy (`buyer` / `influencer` / `gatekeeper` / `champion` / `unknown`), placeholder generation for known-but-unfilled roles, cross-source dedup, CAN-SPAM-aligned opt-out handling, and the shared-roster-pool / per-talent-pitch-history model.
- `docs/outreach_workflow.md` — Phase 3b spec for the AI-generated cold-outreach engine. Covers template selection per decision_role, angle evaluation against the 37-angle library, per-step AI generation (Claude Sonnet for first touch / Haiku for follow-ups), review-before-send queue, Smartlead campaign push, real-time webhook handling, reply classification + cross-roster kill logic, per-talent sender domain setup (SPF/DKIM/DMARC + 2-4 week warmup), and the analytics aggregation layer that captures every email's full provenance for A/B analysis. Includes the default templates (buyer-direct-pitch 4 steps, influencer-warm-intro 3 steps, champion-activation 2 steps; gatekeeper = manual only).
- `.gitignore` — ensures any `*.local.json` or `.env` files containing real keys are never committed.

### Reference taxonomies
Both taxonomy files follow the same shape:
```jsonc
{
  "version": "1.0.0",
  "items": [
    { "id": "kebab-case-slug", "name": "Display Name", "parent": "parent-id-or-null", "aliases": ["search", "terms"] }
  ]
}
```
Top-level entries have `parent: null`; sub-entries reference their parent's `id`. `industries.json` additionally flags `sensitive: true` for categories that are commonly restricted on social platforms or require explicit creator opt-in (alcohol, gambling, tobacco, crypto, etc.).

### How the talent profile links to the taxonomies
The talent profile stores **only `id` slugs**, never display names — that way display labels, translations, and re-namings can change in the taxonomy files without touching any talent record.

| Profile field | References | Validated by |
|---|---|---|
| `content_niches[]` | `data/niches.json` `id` | Schema pattern (`#/$defs/nicheId`) + app load-time check against taxonomy |
| `previous_brands[].industry_id` | `data/industries.json` `id` | Schema pattern (`#/$defs/industryId`) + app load-time check |
| `brand_preferences.preferred_industries[]` | `data/industries.json` `id` | Same |
| `brand_preferences.blocked_industries[]` | `data/industries.json` `id` | Same |
| `brand_preferences.active_exclusivities[].industry_id` | `data/industries.json` `id` | Same |
| `similar_talent[].previous_brands[].industry_id` | `data/industries.json` `id` | Same |

JSON Schema validates the **slug format** (kebab-case). The app validates **slug membership** in the taxonomy on load, since JSON Schema can't dereference external JSON for `enum`.

### Auto-completing `industry_id` from a brand name
When the user types a brand into `previous_brands[].brand`, the app resolves `industry_id` automatically. Resolution order:

1. **Exact match** on `name` in `data/brand_industry_map.json` (case-insensitive).
2. **Alias match** on the `aliases[]` of each entry.
3. **Domain match** if the user pasted a URL or `@domain`.
4. **AI inference fallback** (later phase) — the assistant reads the brand's website / first-page search results and classifies it against `data/industries.json`. The result is then **written back** to `data/brand_industry_map.json` so future lookups are instant and the seed grows.

If multiple matches tie (rare), the app prefers the entry with the more specific (child) `industry_id` over a parent sector.

Each brand record also carries enrichment fields (`hq_country`, `sells_in_countries`, `company_stage`, `typical_campaign_tier`, `creator_program_presence`) used by Brand Discovery searches. Fields are present only when there's a confident value — absence means "not yet enriched"; the app treats missing as unknown rather than assuming a default.

### Niche ↔ Industry affinity (which industries resonate with which niches)
Two complementary models, both kept in sync by `scripts/build_affinity.py`.

**1. Direct model (`niche_industry_affinity.json`)**
Hand-authored edge list. Each niche has up to three tiers of matched industries (`primary` / `secondary` / `tertiary`) and a group-level `evidence` field citing the source of the mapping. Per-edge `overrides[]` can carry edge-specific evidence (case studies, sensitive-vertical flags).

- Edges are **symmetric**: one strength per pair.
- Edges are **quality-floored**: present only if there is either a citable source or a non-generic logical reason. Broad-audience niches (`comedy`, `lifestyle`, `entertainment`) ship with fewer edges by design, not more.
- Sub-niches **inherit** their parent's edges via app-side fallback unless they have their own entry.

Evidence sources used: `iab`, `imh` (Influencer Marketing Hub), `hypeauditor`, `case-study`, `logic`.

**2. Bridged model (via IAB Audience Taxonomy v1.1)**
Uses the official IAB taxonomy as a shared vocabulary between creators and advertisers — the same crosswalk that ad platforms (Meta, Google, TikTok Ads) build internally.

Both sides cite from all three IAB vocabularies for a real, bidirectional bridge:

- `niche_audience_affinity.json` — every niche links to relevant IAB **Interest** (what its audience consumes), **Purchase Intent** (what its audience buys), and **Demographic** (who they are) segments.
- `industry_audience_affinity.json` — every industry links to relevant IAB **Interest** (what content its target customer engages with), **Purchase Intent** (what its target customer is in-market to buy), and **Demographic** segments.
- Niche↔industry affinity is then **computed at runtime** as the overlap of their IAB segment vectors across all three vocabularies.

Talent audience demographics are **IAB-aligned by schema** (the 13 IAB Age Range bands are the only allowed `age_bands` keys), so a specific talent's `audience_demographics` plugs into the bridge directly. The system can therefore compute "best industries for *this* talent" — not just the niche baseline — and explain matches in IAB terms ("matched because both target IAB segment [1377] Family and Parenting and Demo [25-29, 30-34, Female]").

**Why two models?** Direct is fast and trustworthy for ranking. Bridged adds compositional explainability and lets the recommender combine niche signal with the specific talent's real demos. The two are combined in `docs/recommendation_algorithm.md`.

### Recommendation algorithm
The full recipe — how the app combines direct affinity + IAB bridge + past deals + brand preferences + the sensitive flag into a ranked list of industries with `why[]` explanations and `warnings[]` — lives in `docs/recommendation_algorithm.md`. That document is the contract the app will implement.

---

## Phase 2 — Brand Discovery & Targeting

### Output
A per-talent ranked long-list of brand candidates at `data/brand_candidates/current/{talent_id}.json`, validated against `schemas/brand_candidates.schema.json`. Folder is gitignored — the schema and spec are tracked; generated data is not.

### How it works
Two layers, both spec'd before code:

1. **Industry recommendation** (`docs/recommendation_algorithm.md`) — 5-layer score (direct affinity 60% + IAB bridge 25% + past deals 5% + preference boost 10% + policy filters) turns the talent profile into a ranked list of `industry_id`s with `why[]`.
2. **Brand discovery** (`docs/brand_discovery.md`) — 16 independent searches run in parallel, results merged by `brand_id`. A brand surfacing from multiple searches scores higher — count itself is the signal.

The 16 searches cover:

| Group | Searches | Reads |
|---|---|---|
| **Re-engagement** | 1. Previous brands eligible after cool-down | `talent.previous_brands` + dates |
| **Network expansion** | 2. Similar talents' brands<br>3. Competitors of own brands<br>4. Competitors of similar talents' brands<br>5-7. Primary / secondary / tertiary industries | `talent.similar_talent`, `brand_competitors.json`, `brand_industry_map.json`, `niche_industry_affinity.json` |
| **Affinity expansion** | 8. Parent/sibling niches<br>9. Bridged-affinity via IAB demos | `niches.json` parent chain, `niche_audience_affinity.json` + `industry_audience_affinity.json` |
| **Audience-geographic** | 10. Geographic alignment<br>11. Audience life-stage signal | `talent.audience_demographics`, `brand_industry_map.hq_country / sells_in_countries` |
| **Constraint-aware** | 12. Complementary to exclusivities<br>13. Values-aligned brands | `talent.brand_preferences.active_exclusivities`, `values_red_lines` |
| **Graph expansion** | 14. 2nd-degree network | `brand_competitors.json` traversal + roster data |
| **Momentum** | 15. Recently funded (via Exa web search)<br>16. Trending brands (via `last30days` skill) | Exa API + `last30days` skill across Reddit/X/TikTok/YouTube/HN/etc. |

### Qualification filtering
Every candidate carries a `qualification` block with score + signals (positive: active creator program, macro tier, public company, recent funding, high own-brand followers; negative: micro tier, bootstrapped, low followers, B2B vertical). Candidates below score 0.30 are kept in the file but hidden from default view.

### Brand metadata feeds qualification
`brand_industry_map.json` has been enriched with structured metadata that powers both filtering and ranking:

| Field | Coverage | Used by |
|---|---|---|
| `hq_country`, `sells_in_countries` | 290/290 | Search 10 (geo), qualification |
| `company_stage` (`bootstrapped`..`public`..`subsidiary`..`state_owned`) | 290/290 | Qualification, Search 6 inference |
| `typical_campaign_tier` (`nano`..`micro`..`mid`..`macro`..`premium`) | 290/290 | Qualification, future rate-card match |
| `creator_program_presence` (`direct`/`aspire`/`grin`/`ltk`/`shopmy`/`agency_of_record`) | 290/290 | Qualification primary signal |
| `revenue` (USD + as_of_year + source) | 181/290 (62%) | Qualification (enterprise/significant/minimal) |
| `headcount` (LinkedIn-standard bands + source) | 203/290 (70%) | Qualification |
| `social_followers` (per-platform integer counts + as_of_year) | 180/290 (62%) | Qualification (high/moderate/low own-brand follower count) |

Honest-gaps policy: fields are absent when not confident — never null, never fabricated. The full enrichment pipeline for new brands lives in `docs/brand_enrichment_workflow.md`.

### Schedule
- **Monthly cron** (1st of month, per talent): full re-run; catches new re-engagement eligibility, newly-enriched similar talents, freshly-funded brands (Search 15), and 30-day trending brands (Search 16).
- **On talent-profile save/update:** full re-run for that talent.
- **On `brand_industry_map` changes:** incremental re-run of Searches 3, 4, 5, 6, 7.
- **On-demand:** user can trigger from the UI.

### Output preservation
The orchestrator merges fresh discovery output with the previous run's workflow state. Discovery-output fields (`score`, `tier`, `sources`, etc.) are rebuilt every run; workflow-state fields (`status`, `assigned_to`, `user_notes`, `pitch_history`, `first_surfaced_at`) are **preserved**. A user-set `status: "shortlisted"` survives next month's discovery re-run intact. Immutable monthly snapshots are kept under `data/brand_candidates/runs/{talent_id}/run_{date}.json` — needed for the rising-delta / mention-velocity enhancements specced for Search 16.

### Vendor stack (v0.1, for Phase 2)
Two paid dependencies:
- **Exa** — semantic web search for Search 15 + brand enrichment lookups.
- **Anthropic SDK (Claude Haiku 4.5)** — classification + extraction throughout.

Everything else (Reddit / HN / YouTube / X / GitHub / Wikipedia / Yahoo Finance for the `last30days` and enrichment pipelines) uses free public APIs or scrapes. Deferred vendors with criteria-for-adding live in `docs/vendor_roadmap.md`.

---

## Phase 3a — Contact CRM

### Output
A per-brand contact list at `data/brand_contacts/{brand_id}.json`, validated against `schemas/brand_contact.schema.json`. The folder is **gitignored** — contacts are PII and vendor data (Apollo/LinkedIn) is licensed; only the schema and spec are tracked in the repo.

### Shared pool, per-talent pitch history
One contact pool serves the whole roster (no double-paying Apollo for the same person if two talents target the same brand). `pitch_history[]` on each contact carries `talent_id` per entry — so we know which talent pitched whom and when, with a configurable 14-day cooldown to prevent double-pitching the same person across two talents in our roster.

### Contact record sections

| Section | Fields |
|---|---|
| **Identity** | `contact_id` (slug), `brand_id`, `name.{full,first,last,preferred}`, `is_placeholder` |
| **Role** | `title`, `function` (enum: influencer_marketing / brand_partnerships / marketing / brand_management / social_media / pr_comms / creative / founder_ceo / agency_of_record / ...), `seniority` (founder / c_suite / svp / vp / director / manager / ic), `decision_role`, `decision_role_rationale`, `decision_authority_size_band` |
| **Location** | city, country (ISO α-2), timezone |
| **Channels** | `email.{address, verification_status, source, verified_at}` · `linkedin.{url, handle, last_updated, last_activity}` · `social_handles` · `phone` (rare) |
| **Tenure** | `started_at`, `previous_brand`, `is_current` |
| **Qualification** | `score` (0–1), `tier` (qualified / speculative / unqualified), `signals[]` |
| **Workflow** (preserved across re-enrichment) | `tags[]`, `notes`, `pitch_history[]`, `do_not_contact`, `opt_out_at`, `champion_for_talents[]` |
| **Enrichment meta** | `first_discovered_at`, `last_verified_at`, `verification_sources[]`, `confidence` |

### Decision-role taxonomy
A CMO at a $50B+ brand has the title but not the sign-off authority for a $5k Reel deal. The Influencer Marketing Manager 2 levels down is the real `buyer`. The simplified 5-value taxonomy captures who matters for the decision:

| `decision_role` | What they do | Typical at |
|---|---|---|
| `buyer` | Can say yes AND holds the budget for this deal size | IM Manager at mid+ brand; founder/CEO at startup |
| `influencer` (decision-shaping, not the creator role) | Has input but no authority | CMO at megabrand, senior brand manager, brand manager (runs the campaign), procurement/finance reviewer |
| `gatekeeper` | Controls access to the buyer | EA, agency-of-record account manager |
| `champion` | Internal advocate / known fan of this talent or talent type | Junior fan, friend-of-talent inside the company |
| `unknown` | Default until classified | New contacts pending LLM classification |

LLM-driven classification at Step 6 of the enrichment pipeline outputs `decision_role` + a one-line rationale visible to the user. The `decision_authority_size_band` field (separate from role) captures *what deal size* this person can sign off on (`micro` <$5k → `enterprise` $500k+). Blockers and dead-end contacts are captured via free-form `tags[]` rather than a primary role.

### Contact-qualification signals
Ranks contacts *within* a brand (separate from brand-level qualification in Phase 2):

| Direction | Signal | Source |
|---|---|---|
| (+) | `has_verified_email`, `holds_decision_role`, `tenure_at_least_1y`, `recent_linkedin_activity`, `champion_for_other_talents`, `warm_intro_available`, `matches_brand_typical_tier`, `in_target_audience_country` | Apollo + LinkedIn API + pitch_history |
| (−) | `left_brand`, `placeholder_only`, `email_bounced_recently`, `senior_executive_at_large_brand`, `unverified_email`, `no_linkedin_url`, `stale_data` | Same + verification status |

### Triggers
- **Auto:** when a brand surfaces in `brand_candidates` as `tier: primary` AND `qualification.tier ∈ [qualified, speculative]` AND no contacts file exists yet — kicks off in-flight after Brand Discovery completes.
- **Manual:** user clicks "find contacts" for a specific brand.
- **Refresh:** quarterly re-verifies emails; annual re-pulls LinkedIn data.

### Vendor stack (Phase 3 v0.1)
Three confirmed for v0.1:
- **Apollo** — primary employee lookup + email verification (~$0.20–$0.50/contact)
- **LinkedIn API** (user-provided) — freshness check, last-activity, search for contacts Apollo misses
- **Exa** — fallback for brands Apollo doesn't cover (small D2C, niche)
- **Claude Haiku** — decision-role classification + web-search extraction

Deferred to Phase 3 v2: **Hunter.io**, **Clay.com**, **RocketReach** — see `docs/vendor_roadmap.md` for criteria.

### Outreach hygiene & data handling
US project — CAN-SPAM is the primary legal frame. The structures below are standard CRM/email-marketing good practice:
- Folder gitignored — contact PII + licensed vendor data never committed.
- Opt-out / unsubscribe: `opt_out_at` + `do_not_contact: true` keep record (so we don't accidentally re-enrich and re-pitch them later) but exclude from all future outreach across the roster.
- Source disclosure: `verification_sources[]` records every vendor + date + fields they contributed — answerable in seconds if a contact asks how we got their email.
- Vendor terms: Apollo data is licensed; stays in the gitignored folder, never redistributed.
- Per-talent cooldown: 14 days between pitches to the same contact across different talents in our roster — protects deliverability and sender reputation.
- Bounce handling: hard bounces → `verification_status: bounced` permanently for that address; no retry.

### Placeholder contacts
When a target role is known to exist at a brand (e.g. "Nike must have an IM Manager") but no person is found, the pipeline writes a placeholder record (`is_placeholder: true`, name like "Unknown — Influencer Marketing Manager"). Surfaces coverage gaps as a dashboard signal so they can be filled later. Placeholders are filtered from default outreach lists but counted in the per-brand contact coverage stat.

---

## Phase 3b — Outreach

### Output
A running outreach engine that turns qualified contacts into AI-generated email sequences with reply detection, kill-on-reply across the roster, and full per-email analytics. Runs on Smartlead as the send/sequence backend; Claude generates per-step content; our app owns the angle selection, kill logic, and analytics.

### Two layers
- **Template layer** (`schemas/pitch_template.schema.json`) — sequence STRUCTURE (steps, timing, intent per step, preferred angle categories). System ships 3 default templates: `buyer-direct-pitch` (4 steps), `influencer-warm-intro` (3), `champion-activation` (2). `gatekeeper` contacts have no auto-sequence — surfaced for manual handling.
- **Enrollment layer** (`schemas/pitch_enrollment.schema.json`) — RUNNING INSTANCE of a template for a specific (talent, contact) pair, with AI-generated content per step, Smartlead identifiers, engagement events, and outcome classification.

### Angles library
[`data/pitch_angles.json`](data/pitch_angles.json) ships **37 curated angles** across 15 categories. Examples:
- `past_brand_direct_competitor` — talent has worked with a direct competitor of the target brand (strongest competitive proof; strength 0.95)
- `similar_talent_partnered_with_brand` — a similar talent in our system has partnered with this brand (precedent; strength 0.85)
- `iab_demographic_overlap` — strong IAB demographic match (quantitative audience fit; strength 0.80)
- `brand_new_product_launch` — brand recently launched, time-sensitive (strength 0.70)
- `past_relationship_eligible` — re-engagement of a past brand after cool-down (strength 0.95)
- ...plus categories for niche fit, brand momentum, geographic alignment, mutual connection, values alignment, performance proof, timeliness, creative concepts, insider observations, and role-default hooks per decision_role.

Each angle has a trigger condition (when it fires for a given talent+contact+brand combo), applicable decision roles, applicable step numbers, an example phrasing pattern the LLM adapts, and a hand-authored `authored_strength_score`. The AI generation step gets the set of APPLICABLE angles, picks one primary + optional supporting, and weaves them into the email.

### AI generation — L4 personalization (every step)
Per the v0.1 user decision, **every step in every sequence is generated per-contact** (not templated). Step 1 uses Claude Sonnet 4.7 (highest-value content); follow-up steps use Claude Haiku 4.5 (cost optimisation). Full provenance captured per email:
- Which angles were considered and which was picked
- Model + tokens + cost per generation
- Which personalization fields were merged from talent/contact/brand data
- Reasoning trace

Token budget: ~$0.027 per full 4-step sequence. 100 contacts = ~$2.70 in Claude costs.

### Step 1 manual-approval (hard rule)
**The first email of every sequence requires explicit user approval before sending.** Not configurable, not auto-bypassed, not version-dependent — this is a system invariant. Rationale: the first touch is the highest-stakes email; reply rates are driven disproportionately by step 1; once sent, it cannot be unsent.

Follow-ups (steps 2+) require approval in v0.1 too, but auto-approval for follow-ups becomes a per-talent configurable option in v0.2 (with three guardrails: validation score, tone-similarity to previously-approved content, fresh `sensitive_category` flag). Step 1 stays manual regardless of version or per-talent settings.

### Reply detection + kill logic
Smartlead fires a webhook on every reply. Our app:
1. Claude Haiku classifies reply intent: `interested` / `declined` / `out_of_office` / `unrelated` / `unsubscribe_request` / `needs_more_info` / `wrong_person_routed`
2. Extracts structured signals (asked for pricing? meeting? OoO date? routed to whom?)
3. Kills the active sequence AND any other active sequences for the same contact across the roster
4. `interested` → hot lead in talent's UI; `OoO` → pause + auto-resume; `unsubscribe_request` → permanent `do_not_contact: true`

### Headline metric: reply rate
Per the v0.1 user decision, **reply rate (replied ÷ delivered) is the headline UI metric** — most reliable signal in 2026. Apple Mail Privacy Protection has made open rates noisy (auto-loads tracking pixels), so `engagement_summary.human_opens` filters out likely-MPP events. Raw open rate is captured but flagged noisy.

### Per-talent sender domain (deliverability + authenticity)
Each talent has their own sending domain (e.g. `pitches@janedoetalent.com`). Set up during onboarding via 3 DNS records (SPF, DKIM, DMARC). 2-4 week warmup via Smartlead's peer-to-peer network before first cold send. Per-talent reputation = no cross-contamination, brand recognises the talent's identity, fully Gmail/Yahoo 2024 compliant.

### Email-only in v0.1
Phase 3b v0.1 sends **email only**. LinkedIn outreach (DMs / InMails / connection requests as part of a sequence) is deferred to v2. The pitch_template schema restricts `channel` to `email`; the orchestrator rejects any non-email step. LinkedIn API is still in v0.1 — but for **contact enrichment** (verifying Apollo data freshness, finding contacts Apollo misses), not for sending. When v2 adds LinkedIn-channel sending we'll evaluate vendors (Sales Nav API vs Closely / Expandi / La Growth Machine), automation-policy compliance, and per-talent LinkedIn account warmup.

### Vendor stack (Phase 3b v0.1)
- **Smartlead** — send + sequence + warmup + reply detection (~$94/mo Pro per talent mailbox)
- **Claude (Anthropic SDK)** — content generation + reply classification (~$0.027 per full sequence)

That's the entire vendor footprint for Phase 3b. Resend was considered but rejected — their ToS prohibits cold outreach (transactional API). Hunter.io / Clay.com / RocketReach deferred to v2 if Apollo coverage gaps emerge.

### Analytics — every email tracked, every angle measured
[`scripts/analyze_outreach.py`](scripts/analyze_outreach.py) rolls every step record into A/B sliceable aggregates:

| Slice | What it answers |
|---|---|
| by_angle | Which angles have the best reply rate |
| by_angle_pair | Whether primary+supporting combinations beat singletons |
| by_decision_role | Which angles work for buyers vs influencers vs champions |
| by_template | Which templates convert best |
| by_step_number | When in the sequence replies happen |
| by_brand_tier / brand_industry | Which brand profiles respond |
| by_talent | Which of our roster's talents convert best |
| by_send_dow / send_hour | Day-of-week / time-of-day effects |
| by_subject_pattern | Length / question / emoji effects |
| by_sender_domain | Per-domain inbox placement |

Each slice computes: sent, delivered, reply rate, positive reply rate, human open rate (MPP-filtered), click rate, bounce rate, mean time-to-reply, total cost, cost per positive reply.

**v0.1 explicit non-goal:** the analyzer does NOT auto-update `pitch_angles.json` `authored_strength_score`. Output is for human review only. Users edit angles manually as they learn. Closed-loop auto-tuning is a v2 deliverable.
