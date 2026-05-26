# NATIV2 — AI Influencer Marketing Assistant

## Goal

Build an AI-powered assistant that helps an influencer (or a roster of influencers) **find, connect with, and close deals with brands** to promote their products. The assistant should automate the manual grind of brand discovery, outreach, negotiation, and deal admin — while keeping the creator in control of voice, values, and final approvals.

## Phases

| # | Phase | Status | Purpose |
|---|-------|--------|---------|
| 1 | **Talent Profile** | v0.1 spec + data shipped | Capture everything the system needs about the creator(s) — identity, audience, history, rates, similar talents. The foundation every later phase reads from. |
| 2 | **Brand Discovery & Targeting** | v0.1 spec + data shipped | For a given talent, produce a ranked list of industries to pitch and a ranked long-list of specific brands within them — with qualification filtering, sensitive-vertical warnings, and re-engagement on a monthly cron. |
| 3 | **Outreach** | TBD | Take the ranked brand list, find the right contact (Apollo et al.), draft + send personalised pitches, track replies, hand off to negotiation. |
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
│ Phase 3  OUTREACH (TBD)                                            │
│   Apollo for contact discovery → personalised pitch → reply track  │
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

### Vendor stack (v0.1)
Only two paid dependencies:
- **Exa** — semantic web search for Search 15 + brand enrichment lookups.
- **Anthropic SDK (Claude Haiku 4.5)** — classification + extraction throughout.

Everything else (Reddit / HN / YouTube / X / GitHub / Wikipedia / Yahoo Finance for the `last30days` and enrichment pipelines) uses free public APIs or scrapes. Deferred vendors with criteria-for-adding live in `docs/vendor_roadmap.md`.
