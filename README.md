# NATIV2 — AI Influencer Marketing Assistant

## Goal

Build an AI-powered assistant that helps an influencer (or a roster of influencers) **find, connect with, and close deals with brands** to promote their products. The assistant should automate the manual grind of brand discovery, outreach, negotiation, and deal admin — while keeping the creator in control of voice, values, and final approvals.

## Phases

| # | Phase | Purpose |
|---|-------|---------|
| 1 | **Talent Profile** | Capture everything the system needs to know about the creator(s) — who they are, who their audience is, what they've done, what they cost, who they look like in the market. This is the foundation every later phase reads from. |
| 2 | _TBD_ | (To be defined by the user.) |
| 3 | _TBD_ | (To be defined by the user.) |

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
- `data/brand_industry_map.json` — seed lookup of well-known brand names → `industry_id` (290 brands, all enriched with `hq_country`, `sells_in_countries`, `company_stage`, `typical_campaign_tier`, `creator_program_presence` for Brand Discovery searches). Used by the app's auto-complete and grows over time.
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
- `docs/vendor_roadmap.md` — single source of truth for external-service decisions. Confirms **Exa** as the v0.1 web-search provider (Search 15). Catalogues deferred vendors with criteria for when to add each: ScrapeCreators (Search 16 visual platforms), Owler (competitor maintenance), Modash/HypeAuditor (brand DB bulk import), Exploding Topics (pre-trend detection), Product Hunt API (day-of launches), Tribe Dynamics EMV (top-spending brands per category), SimilarWeb (audience-overlap competitors), Crunchbase (structured funding data), Apollo (Phase 2 outreach contact discovery), plus alternatives for each. Includes the env-var inventory for all current + deferred services.
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
