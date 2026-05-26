# Brand Enrichment Workflow

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the system that takes a brand from "name only" to fully populated in `data/brand_industry_map.json`.

**Pairs with:**
- `docs/brand_discovery.md` — the consumer of this data (15 of 16 searches need a populated `brand_industry_map`).
- `docs/vendor_roadmap.md` — the external services this workflow uses.
- `scripts/enrich_brand_map.py` — the manual/seed enrichment script; the runtime workflow specced here uses the same fields and policies.

## Goal

For every brand in `data/brand_industry_map.json`, populate **every field in the schema** with confident values, honestly leaving fields empty where we don't have data. The end state is a brand record that can power:
- Industry resolution (the original purpose)
- Brand Discovery (Searches 3, 5–10, 14)
- Qualification scoring (revenue, headcount, follower counts, creator-program presence)
- Geographic filtering (hq_country, sells_in_countries)
- Tier matching (typical_campaign_tier)

**Honesty floor:** never fabricate. Every field has `source` provenance; unknown values are omitted (absence ≠ null ≠ zero).

## Schema target (full brand record)

```jsonc
{
  "name": "Liquid Death",
  "industry_id": "bottled-water",
  "aliases": ["liquid death mountain water"],
  "domain": "liquiddeath.com",

  // --- core enrichment (5 fields) ---
  "hq_country": "US",
  "sells_in_countries": ["US", "GB", "CA"],
  "company_stage": "private_growth",
  "typical_campaign_tier": "mid",
  "creator_program_presence": ["direct"],

  // --- financials ---
  "revenue": {
    "amount_usd": 350000000,
    "as_of_year": 2024,
    "source": "press_release"
  },
  "headcount": {
    "band": "51_200",
    "source": "linkedin"
  },

  // --- social presence ---
  "social_followers": {
    "instagram": 3000000,
    "tiktok": 5500000,
    "as_of_year": 2025
  }
}
```

12 fields total (4 identity + 5 core + 2 financial + 1 social block).

## When this workflow runs

Three triggers:

| Trigger | When | Scope |
|---|---|---|
| **A. Seed expansion** | On demand or quarterly | Bulk-enrich N new brands from a list (e.g. one-month Modash subscription dump) |
| **B. New-brand discovery writeback** | Continuously during Brand Discovery runs | One brand at a time — Searches 15 and 16 surface novel brands; the orchestrator enriches them in-flight before adding to the candidate file |
| **C. Refresh stale brands** | Annually per brand | Re-resolve revenue, headcount, follower counts as numbers age; mark `last_enriched_at` so the orchestrator knows when to refresh |

## The 9-step pipeline (per brand)

Each step pulls data and stops as soon as it has a confident value. Steps run in cheap-to-expensive order; later steps are skipped if earlier ones already filled the field.

### Step 1 — Identity resolution
**Input:** raw brand string from a user, scraper, or LLM extraction.
**Steps:**
1. Normalise: trim, lowercase, strip `Inc/Ltd/Plc/LLC/Co./Corp` suffixes, kebab-case.
2. Check existing `brand_industry_map.json` for exact name match → if found, **skip to refresh logic** (the rest of this pipeline becomes "is anything missing or stale?").
3. Check `aliases[]` of every existing brand for a match.
4. If a URL/domain was supplied, check `domain` field on every record.
**Outputs:** confirmed `name`, `aliases[]` (add the surface form as an alias if it differs from the canonical name), `domain` (if known).
**Skip-conditions:** if the name is ambiguous (e.g. "Apollo" → Apollo.io or Apollo Tyres?), surface for human disambiguation rather than guessing.

### Step 2 — Domain resolution
**If `domain` is not yet set:**
1. Query **Exa** with the brand name and a hint of the category (e.g. `"Liquid Death water brand official site"`).
2. Take the top result that matches the brand name with high confidence; extract the root domain.
3. Validate via HTTP HEAD that the domain serves a 200/3xx.
**Outputs:** `domain` populated; `aliases[]` extended with any surface forms found.
**Fallback:** if no confident domain, leave blank — it will retry on the next enrichment cycle.

### Step 3 — Industry classification
**If `industry_id` is not yet set:**
1. Use Exa `/contents` to fetch the brand's homepage (and `/about` if present).
2. LLM (Claude Haiku) classifies the extracted text against `data/industries.json` — outputs `industry_id` + confidence + a one-sentence rationale.
3. If confidence ≥ 0.8, accept; otherwise surface for human review (queued in an `enrichment_review.json` file).
**Outputs:** `industry_id`.

### Step 4 — HQ country and primary markets
**Sources tried in order:**
1. Brand's official website footer / "Contact us" page (Exa `/contents`).
2. Domain TLD heuristic (`.co.uk` → GB hint; not definitive).
3. LLM web-search via Exa for "`<brand>` headquartered" / "`<brand>` company information".
4. Wikipedia infobox (Exa search + LLM extraction).
**Outputs:**
- `hq_country` — ISO 3166-1 alpha-2.
- `sells_in_countries` — either `"global"` (if the brand explicitly markets globally) or an array of ISO codes (from "where to buy" pages, regional sites, store-locator data).
**Skip-conditions:** if no clear HQ country, leave blank.

### Step 5 — Company stage
**Source ladder:**
1. **Public-company check:** ticker lookup against US/UK/EU/JP exchanges (free via Yahoo Finance scrape or LLM web-search). If listed → `company_stage: "public"`.
2. **Subsidiary check:** if Wikipedia infobox or LLM search shows "subsidiary of X" or "owned by X" → `company_stage: "subsidiary"`; capture parent name in `parent_company` field (TBD in v0.2).
3. **Funding history (private companies):** Exa search for "`<brand>` Series A funding" / "`<brand>` raised". LLM extracts the latest round.
   - Pre-seed → `seed`
   - Seed → `seed`
   - Series A/B/C/D → `series_a` / `series_b` / `series_c` / `series_d`
   - "Profitable bootstrapped" or no funding history → `bootstrapped`
   - Late-stage / pre-IPO → `private_growth`
4. **State-owned check:** explicit government ownership → `state_owned` (rare; flag manually).
**Outputs:** `company_stage` with one of the enum values.
**Fallback:** if no confident classification, set `company_stage: "unknown"` (explicit, distinct from omission).

### Step 6 — Typical campaign tier (creator-marketing budget proxy)
This is the most inferential field. Use the following decision rules:
- `company_stage == "public"` AND `revenue > $1B` → `premium` or `macro` (depending on industry — luxury and global CPG are `premium`; everything else `macro`).
- `company_stage == "private_growth"` AND `revenue > $200M` → `macro`.
- `private_growth` with `revenue $50M-$200M` → `mid`.
- `seed`/`series_a` or `revenue < $50M` → `micro`.
- `bootstrapped` with no funding visible → `micro` or `nano`.
- **Reality check via observed signals:** if the LLM web-search surfaces actual recent creator partnerships at known fee bands (e.g. "Brand X paid $5k for an IG Reel"), override the inferred tier.
**Outputs:** `typical_campaign_tier`.
**Fallback:** `unknown` if both stage and revenue are missing.

### Step 7 — Creator program presence
**Sources tried:**
1. Exa search: `"<brand> creator program"`, `"<brand> ambassador program"`, `"<brand> influencer marketing"`.
2. Check known creator-marketplace sites (Aspire, Grin) for the brand's listing (when Aspire/Grin API access is added per `vendor_roadmap.md`).
3. LinkedIn search for the brand's "Influencer Marketing Manager" / "Creator Partnerships" job titles → presence implies an internal team.
4. Default to `["direct"]` if the brand is established (`company_stage` in `[public, private_growth, subsidiary]`) — almost all sizeable brands accept direct pitches even without a formal program.
**Outputs:** `creator_program_presence` array of enum values.

### Step 8 — Financials (revenue + headcount)
**Revenue:**
1. **Public companies:** scrape the most recent 10-K / annual report cover page or the brand's investor-relations page (LLM extracts the total revenue figure + fiscal year). `source: "public_filing"`.
2. **Private companies:** Exa search for "`<brand>` annual revenue", "`<brand>` £X million", "`<brand>` $X turnover". LLM extracts press-release figures. `source: "press_release"`. Always round to nearest $100M (or $1B for >$10B brands) to reflect the looser confidence.
3. **Subsidiaries:** if parent reports brand-level revenue (e.g. The North Face under VF Corp), extract. Otherwise omit.
4. **Estimate of last resort:** if a Forbes profile / industry analyst report cites a credible estimate, use `source: "reported_estimate"` — but flag clearly with lower confidence.
**Outputs:** `revenue.{amount_usd, as_of_year, source}`. **Omit entirely if no confident figure.**

**Headcount:**
1. LinkedIn company page → official band (LinkedIn uses the standard 1–10 / 11–50 / 51–200 / 201–500 / 501–1k / 1k–5k / 5k–10k / 10k+).
2. Public-company filings (employee count is required disclosure in most jurisdictions).
3. Press releases for funding rounds often quote headcount.
4. As a sanity-check: revenue ÷ ~$200k-per-employee-equivalent gives a rough order of magnitude.
**Outputs:** `headcount.{band, source}`. **Omit if not confident.**

### Step 9 — Social follower counts
For each of `[instagram, tiktok, youtube, twitter_x, facebook, linkedin, pinterest]`:
1. **Identify the brand's official account** on the platform (Exa search for `"<brand> Instagram official"`, or scrape the brand's homepage social-icon links).
2. Pull the current follower count:
   - **Without ScrapeCreators key** (default v0.1 stack): use platform-specific scrapers where free APIs exist (Instagram requires browser-emulated scrape; X requires session; YouTube has free API).
   - **With ScrapeCreators key** (future): use it for TikTok / IG / Threads / Pinterest at once.
3. **Round per the honesty policy:**
   - `<1M` → nearest 100k
   - `1M–10M` → nearest 100k–500k
   - `10M–100M` → nearest 1M
   - `100M+` → nearest 10M
4. Store as integer counts in `social_followers.{platform}` + a single `as_of_year` for the block.
**Outputs:** `social_followers` object. Platforms where the brand has no meaningful presence (or no confident count) are omitted entirely.
**Fallback:** if no platform data is found, omit the whole `social_followers` block.

## Honesty-floor policy (applies to every step)

This is the rule that makes the data trustworthy:

| Situation | Action |
|---|---|
| Source has a clear, dated value | Populate field with `source` set |
| Source is ambiguous / multiple conflicting figures | Use the most recent confident value; mark `source: "reported_estimate"` |
| No source found after exhausting the ladder | **Omit the field.** Do not set null, do not set zero, do not guess |
| Value found is clearly stale (>2 years for revenue, >1 year for follower counts) | Use it but flag in `enrichment_meta` for refresh priority |
| Multiple brands match the input name (disambiguation needed) | Halt and queue for human review; do not pick one |

The orchestrator should never feel pressure to fill a field. Sparse-but-honest beats dense-but-fabricated — downstream qualification scoring already accounts for missing fields without penalising.

## Per-brand enrichment metadata (proposed addition)

A new optional sub-object on every enriched brand record, tracking when each field was last verified and from what source. Not yet shipped to the schema — proposed for v0.2:

```jsonc
"enrichment_meta": {
  "last_enriched_at": "2026-05-26T00:00:00Z",
  "enrichment_pipeline_version": "0.1",
  "stale_fields": ["social_followers"],   // fields needing refresh
  "review_required": false,               // true if any step hit an ambiguity
  "field_sources": {
    "hq_country":           { "source": "wikipedia",   "verified_at": "2026-05-26" },
    "revenue":              { "source": "public_filing_10k", "verified_at": "2025-12-15" },
    "social_followers":     { "source": "ig_scrape",   "verified_at": "2025-04-10" }
  }
}
```

This lets the refresh job (trigger C above) know which fields to re-pull without re-running the whole pipeline.

## Tools used per step

| Step | Tool / API | Cost | Required? |
|---|---|---|---|
| 1. Identity resolution | Code only (string normalisation) | Free | ✅ |
| 2. Domain resolution | **Exa** `/search` + HTTP HEAD | Exa quota | ✅ |
| 3. Industry classification | **Exa** `/contents` + Claude Haiku | Exa + Haiku tokens | ✅ |
| 4. HQ + markets | **Exa** + Claude Haiku for extraction | Exa + Haiku tokens | ✅ |
| 5. Company stage | **Exa** + Yahoo Finance scrape + Wikipedia | Exa quota; rest free | ✅ |
| 6. Campaign tier | Code only (derived from stage + revenue) | Free | ✅ |
| 7. Creator program presence | **Exa** + Claude Haiku; future: Aspire/Grin APIs | Exa + Haiku; future paid APIs | ✅ |
| 8. Revenue + headcount | **Exa** for press; LinkedIn scrape for headcount; SEC EDGAR scrape for public filings | Exa quota; rest free | ✅ |
| 9. Social followers | Platform-specific scrapers (free for IG/X/YT); future: ScrapeCreators for TikTok/Threads/Pinterest | Free without ScrapeCreators; ~$0.01–$0.05 per fetch with it | Optional per-platform |

**Total vendor footprint:** Exa + Claude (Anthropic SDK) are the only paid dependencies for v0.1.

## Orchestration: how this fits with Brand Discovery

The brand-enrichment pipeline runs in two modes:

**Mode 1: In-flight (during Brand Discovery)**
- When Searches 15 or 16 extract a brand name that's not in `brand_industry_map.json`, the orchestrator triggers the pipeline above on that brand before adding it to the candidate file.
- Runs synchronously per brand (latency ~5–15s per brand depending on how many steps need external calls).
- Writeback to `brand_industry_map.json` happens immediately — the next talent's discovery run sees the new brand.

**Mode 2: Bulk seed expansion**
- Quarterly (or after a Modash/HypeAuditor bulk import) → batch of new brand names.
- Runs all 9 steps in parallel per brand, with a shared rate-limit budget against Exa.
- Atomic write to `brand_industry_map.json` at the end (with file locking if multi-process).

**Mode 3: Refresh**
- Annually per brand → re-run Steps 5, 8, 9 (the fields most likely to be stale).
- Steps 1–4 and 7 only re-run if `enrichment_meta.review_required == true`.

## State machine

```
NEW BRAND NAME ENCOUNTERED
        │
        ▼
   ┌─────────────┐
   │ Step 1      │ ← exact match in brand_industry_map.json?
   │ Identity    │
   └─────────────┘
        │
        ├─ YES → refresh logic (check stale_fields)
        │
        └─ NO  → continue
              │
              ▼
        ┌─────────────────────────────┐
        │ Steps 2–9 in dependency      │
        │ order, parallel where        │
        │ possible. Each step skipped  │
        │ if field already populated.  │
        └─────────────────────────────┘
              │
              ▼
   ┌─────────────────────┐
   │ Validation pass     │ ← schema-validate the new record
   └─────────────────────┘
              │
              ├─ FAIL → enrichment_review.json + human review
              │
              └─ PASS → atomic write to brand_industry_map.json
                          + log to enrichment_meta
                          + emit "brand_added" event for downstream consumers
```

## Quality gates before commit

Before writing a new or updated brand record to `brand_industry_map.json`:

1. **Schema validation** — record conforms to the (planned) `brand_industry_map.schema.json` (not yet shipped — proposed for v0.2).
2. **Industry_id cross-check** — value exists in `industries.json`.
3. **Country-code validation** — `hq_country` and `sells_in_countries` codes exist in ISO 3166-1.
4. **Honesty check** — every populated field has a `source` (or is one of the enum-only fields like `company_stage`).
5. **De-dup check** — no other record in `brand_industry_map.json` has the same `domain` or a name that normalises to the same slug.

Failed quality gates → record goes to `enrichment_review.json` queue, not the live file.

## Failure handling

| Failure | Behaviour |
|---|---|
| Exa quota exhausted | Pause enrichment; resume next cycle. In-flight discovery falls back to "industry unknown" for the affected brand. |
| Claude API error | Retry with exponential backoff (3 attempts); on persistent failure, queue for next batch. |
| LLM hallucinates an industry not in `industries.json` | Validation fails; queue for human review. |
| Wikipedia / Yahoo Finance unreachable | Skip step; mark field as unknown for this run. |
| Brand name is ambiguous (multiple matches) | Halt pipeline; surface to `enrichment_review.json` with all candidate disambiguations. |
| Brand domain returns 404 | Try `findSimilar` on Exa with the brand name; if no replacement found, mark `domain` as unknown. |

## Open questions for v0.2

1. **Should `enrichment_meta` ship to the live schema now?** Tracking per-field provenance + freshness is useful but adds noise to every record. May be worth gating behind a flag.
2. **Should we add `parent_company` for subsidiaries?** Useful for rollup queries ("show all brands owned by VF Corp") but requires authoring or scraping a parent-child graph.
3. **Should `social_followers` carry engagement-rate too?** A 5M-follower account with 0.5% ER is much less valuable than a 500k-follower account with 8% ER for creator-marketing partnerships. Adds an enrichment step (per-platform recent-post sampling).
4. **Refresh prioritisation.** Without a budget cap, the annual refresh of 290+ brands across 9 steps could consume meaningful Exa quota in one batch. Prioritisation: refresh brands appearing as candidates most often first, then the long tail.
5. **Manual override layer.** If a human user overrides a field (e.g. corrects an LLM-inferred `industry_id`), how do we prevent the next enrichment cycle from overwriting it? Proposed: `field_overrides[]` array that the pipeline always respects.
6. **Multi-brand parent companies.** When a parent company is added (LVMH), do we auto-create child records for its brands? Requires a brand-portfolio data source.
