# Brand Discovery — Long-List Generation

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the system that takes a complete talent profile and produces a ranked long-list of every brand worth pitching.

Reads: `talents/{id}.json` + the full `data/` directory + (eventually) external APIs.
Writes: `data/brand_candidates/{talent_id}.json` (one per talent, rebuilt on schedule + on profile change).

Pairs with:
- `docs/recommendation_algorithm.md` — once an industry is recommended, this doc finds the *brands* within it.
- `docs/onboarding_workflow.md` — produces the input this doc reads.

---

## Goal

Produce an **exhaustive** ranked list of brand-deal candidates for a given talent — not just the obvious primary-industry matches, but the long tail of brands that are genuinely reachable. The list is built by running **many independent searches in parallel** and merging the results. A brand that surfaces from multiple searches is a higher-confidence candidate than one that surfaces from one — the count itself is the ranking signal.

---

## Output shape

`data/brand_candidates/{talent_id}.json`:

```jsonc
{
  "talent_id": "jane-doe",
  "generated_at": "2026-05-26T14:32:00Z",
  "search_run_id": "run_2026-05-26_001",
  "candidates": [
    {
      "brand": "Lululemon",
      "industry_id": "activewear",
      "score": 0.84,
      "tier": "primary",
      "found_in_searches": 6,
      "sources": [
        { "search": "primary_industry", "weight": 0.30, "note": "fitness primary -> activewear; well-documented creator program" },
        { "search": "competitor_of_previous", "weight": 0.25, "note": "competitor of Gymshark (in talent.previous_brands)" },
        { "search": "demographic_bridge", "weight": 0.15, "note": "shared IAB Interest [Fitness, Healthy Living] + Demo [25-29, 30-34, Female]" },
        { "search": "similar_talent_worked_with", "weight": 0.10, "note": "@othercreator worked with Lululemon (campaign 2025-11)" },
        { "search": "geographic_alignment", "weight": 0.04, "note": "sells in GB (talent's #1 market, 54% audience)" },
        { "search": "values_aligned", "weight": 0.00, "note": "neutral on talent's red lines" }
      ],
      "warnings": [],
      "blocked_reason": null,
      "next_action_hint": "Cold outreach; no prior contact"
    },
    {
      "brand": "Athletic Greens (AG1)",
      "industry_id": "supplements-brands",
      "score": 0.71,
      "tier": "primary",
      "found_in_searches": 4,
      "sources": [
        { "search": "primary_industry", "weight": 0.30, "note": "fitness primary -> supplements-brands" },
        { "search": "preferred_industry", "weight": 0.10, "note": "in talent.brand_preferences.preferred_industries" },
        { "search": "demographic_bridge", "weight": 0.20, "note": "shared IAB PI [Drugstores, Health Medical], Demo [25-39, Female-leaning]" },
        { "search": "active_creator_program", "weight": 0.11, "note": "known to run large monthly creator drops (case study)" }
      ],
      "warnings": [],
      "blocked_reason": null,
      "next_action_hint": "Apply via their creator program form; mention shared interest in nutrition"
    },
    {
      "brand": "Gymshark",
      "industry_id": "activewear",
      "score": 0.95,
      "tier": "re-engage",
      "found_in_searches": 3,
      "sources": [
        { "search": "previous_brand_reengage", "weight": 0.60, "note": "Previous campaign 2025-09; 8 months ago; eligible per cool-down" },
        { "search": "primary_industry", "weight": 0.25, "note": "fitness primary -> activewear" },
        { "search": "demographic_bridge", "weight": 0.10, "note": "matches talent demos" }
      ],
      "warnings": [],
      "blocked_reason": null,
      "next_action_hint": "Re-engage with existing contact; reference last campaign performance"
    }
  ],
  "blocked": [
    { "brand": "Nike", "reason": "active_exclusivity in sportswear until 2026-12-31" },
    { "brand": "DraftKings", "reason": "industry `gambling` in blocked_industries" }
  ],
  "stats": {
    "total_candidates": 187,
    "by_tier": { "re-engage": 6, "primary": 42, "secondary": 78, "tertiary": 61 },
    "by_source_count": { "1": 89, "2": 51, "3": 28, "4": 12, "5+": 7 }
  }
}
```

---

## The 14 searches (runnable today on current JSON)

Each search is independent; all run in parallel; results merge by brand name + industry.

### Group A — Re-engagement (highest conversion likelihood)

#### Search 1 — Previous brands eligible for re-engagement
**Reads:** `talent.previous_brands[]` + `talent.previous_brands[].campaign_date`.
**Logic:** include each previous brand where `today - last_campaign_date ≥ cool_down_days` (default 180 days; configurable per brand if specified in `previous_brands[].cool_down_override`).
**Output tag:** `tier: "re-engage"`. These get a 0.60 weight — highest of any source because warm contacts convert far better than cold.
**Schedule:** monthly cron job per talent. Surfaces newly-eligible re-engagements as their cool-down elapses.
**Cool-down logic:**
- Default: 180 days from last campaign end (or campaign date if no end date).
- Override per brand: if `previous_brands[].cool_down_override.days` is set, use that.
- Permanent block: if `previous_brands[].do_not_recontact == true` (set after a soured deal), never re-surface.

### Group B — Network expansion

#### Search 2 — Brands similar talents have worked with
**Reads:** `talent.similar_talent[].previous_brands[]` (populated by AI research in onboarding Step 9).
**Logic:** flatten all brands from all similar talents; for each brand, count how many similar talents worked with it. A brand 3+ similar talents have worked with is a very strong signal.
**Edge:** filter out brands already in `talent.previous_brands` (those are covered by search 1).

#### Search 3 — Direct competitors of talent's previous brands
**Reads:** `talent.previous_brands[].industry_id` + `data/brand_industry_map.json`.
**Logic:** for each industry that's appeared in the talent's brand history, return every other brand in `brand_industry_map.json` with the same `industry_id`. Filter out the talent's own previous brands (already covered).
**Note:** "competitor" is loose without a true competitor graph (see future search 23). For now, same-industry is the proxy.

#### Search 4 — Direct competitors of similar talents' brands
**Reads:** Search 2 output + `data/brand_industry_map.json`.
**Logic:** same as search 3 but applied transitively to similar talents' brand history. Catches brands one degree further out from the talent's direct experience.

#### Search 5 — Brands in primary-tier industries for talent's niches
**Reads:** `talent.content_niches[]` → `data/niche_industry_affinity.json` `primary[]` → `data/brand_industry_map.json` filtered by those `industry_id`s.
**Logic:** the direct affinity matrix's strongest tier, materialised as brands.
**This is the largest single source by volume.** Expect 50–100 brands surfaced per talent.

#### Search 6 — Brands in secondary-tier industries
Same as search 5 but using `secondary[]`. Lower weight; broader coverage.

#### Search 7 — Brands in tertiary-tier industries
Same as search 5 but using `tertiary[]`. Lowest weight; surfaces non-obvious matches the talent might not have considered.

### Group C — Affinity expansion (uses fuller depth of the taxonomy)

#### Search 8 — Brands in parent and sibling niches' industries
**Reads:** `talent.content_niches[]` + `data/niches.json` parent chain + `data/niche_industry_affinity.json`.
**Logic:** for each niche, walk up to its parent and across to its siblings. Run search 5 against those expanded niches. Surfaces brands that target the broader category audience.
**Example:** talent has `pilates` → also pull industries for `fitness` (parent), `yoga`, `crossfit` (siblings).

#### Search 9 — Bridged-affinity industries via talent's specific demographics
**Reads:** `talent.audience_demographics` + `data/niche_audience_affinity.json` + `data/industry_audience_affinity.json` + `data/iab_audience_taxonomy_v1.1.json`.
**Logic:**
1. Build the talent's IAB segment vector from their actual demographics (per `recommendation_algorithm.md` § Layer 2 Step A).
2. For every industry in `industry_audience_affinity.json`, compute IAB segment overlap.
3. Surface industries with overlap ≥ threshold that are *not already* in searches 5–7.
4. Pull brands in those industries from `brand_industry_map.json`.
**Why it matters:** catches industries the niche-direct matrix doesn't list but the talent's actual audience demographics match well. A fitness creator with a 75% female 25-39 audience surfaces `femtech`, `beauty-personal-care`, `dental-services` even though those aren't in `fitness → primary/secondary/tertiary`.

### Group D — Audience-geographic

#### Search 10 — Geographic alignment
**Reads:** `talent.audience_demographics.top_countries[]` + `data/brand_industry_map.json` (filter by domain TLD or future `hq_country` / `sells_in_countries` fields).
**Logic v0 (today):**
- Map talent's top 3 audience countries to TLDs (`GB → .co.uk`, `DE → .de`, `JP → .jp`, etc.).
- For each candidate brand already surfaced by other searches, **boost** the score if its domain matches one of the audience TLDs.
- *Discover* mode (smaller v0): for each top country, scan `brand_industry_map.json` for brands with matching TLDs that haven't been surfaced by other searches and are in relevant industries.
**Logic v0.2 (after enrichment — see § Structural moves):** filter on `hq_country` and `sells_in_countries` for precise geo matching.

#### Search 11 — Audience life-stage signal
**Reads:** dominant band in `talent.audience_demographics.age_bands` + `data/industry_audience_affinity.json` + IAB Demographic mappings.
**Logic:** identify the talent's #1 audience age band. Pull industries whose `demographic_segments` include that band's IAB ID **and** whose typical purchase intent corresponds to that life stage:
- 18-24 dominant → `fast-fashion`, `dating-apps`, `apps-platforms`, `fintech-neobanks` (BNPL), `coding-bootcamps`, beauty
- 25-29 dominant → `fintech-neobanks`, `dating-apps`, `travel-hospitality`, beauty, `apps-platforms`
- 30-34 dominant → `mortgages`, `baby-kids`, `home-living`, `family-travel`, `insurance`
- 35-44 dominant → `home-improvement`, `auto-oems`, `kids-edutainment`, `financial-services`, `wedding`
- 45+ dominant → `mortgages`, `vision-care`, `pets-industry`, `cruises`, `health-pharma`
**This is a small additional booster** on top of search 9, but explicit life-stage targeting often surfaces high-converting industries the broader bridge undervalues.

### Group E — Constraint-aware

#### Search 12 — Complementary categories around active exclusivities
**Reads:** `talent.brand_preferences.active_exclusivities[]` + `data/niche_industry_affinity.json`.
**Logic:** for each active exclusivity (e.g. Nike exclusive in `sportswear` until 2026-12-31):
1. Block the exclusivity industry and any direct-competitor brands (already handled by the policy layer in the algorithm spec).
2. **Surface adjacent industries that share niche-level affinity but aren't conflicted.** Look at every niche where the blocked industry appears, then push the *other* industries in the same niche group hard — those are categories the talent has bandwidth for and that audience-wise still resonate.
**Example:** Nike exclusivity in `sportswear` for a `fitness` creator → push `sports-nutrition`, `wearables`, `fitness-equipment`, `gyms-studios` (also `fitness` primary). The talent can run these in parallel with the Nike deal without conflict.

#### Search 13 — Values-aligned brands (positive use of `values_red_lines`)
**Reads:** `talent.brand_preferences.values_red_lines[]` + `data/brand_industry_map.json` + LLM evaluation.
**Logic:** today red lines only filter brands out. Use them to also *recruit*:
1. For each red-line statement (e.g. "no diet culture", "no fast fashion", "no fossil fuels"), LLM-classify candidate brands as `aligned` / `neutral` / `conflict`.
2. Brands tagged `aligned` get a positive score modifier (e.g. +0.05); brands tagged `conflict` are filtered (already covered by policy layer).
**Example:** "no diet culture" red line surfaces body-positive / HAES-aligned brands (Aerie, Knix, Athleta, Universal Standard) with a positive nudge.

### Group F — Graph expansion (2nd-degree network)

#### Search 14 — Brands the talent's previous brands' competitors work with
**Reads:** `talent.previous_brands[]` → industries → competitor brands (search 3 output) → cross-reference with `talent.similar_talent[].previous_brands[]` and other talents in our system (if multi-talent roster).
**Logic:** find creators who worked with the talent's previous brands' competitors → look at *those* creators' brand history → identify brands that appear repeatedly. These are brands clustered around the same competitive set.
**Why it matters:** surfaces cross-industry patterns the industry filter misses. If Tesla buyers also frequently engage with premium audio brands, a creator who's worked with Tesla should see Sennheiser surfaced even though `ev-brands` and `audio-equipment` aren't strongly linked in the affinity matrix.
**Limit:** depends on roster size. With 1 talent and few similar talents, this is thin. Grows valuable as the roster + similar-talent database grows.

---

## Scoring & deduplication

### Merge

After all 14 searches run, merge by `(brand, industry_id)` tuple. A brand surfacing from multiple searches accumulates `sources[]` entries.

### Score

```
score(brand | talent) = min(1.0, Σ sources[i].weight)
```

Source weights (default; tunable):

| Source | Weight |
|---|---|
| `previous_brand_reengage` | 0.60 |
| `primary_industry` | 0.30 |
| `competitor_of_previous` | 0.25 |
| `secondary_industry` | 0.20 |
| `demographic_bridge` | 0.15–0.25 (scales with overlap count) |
| `similar_talent_worked_with` | 0.10–0.20 (scales with how many similar talents) |
| `preferred_industry` | 0.10 |
| `competitor_of_similar_talent` | 0.10 |
| `parent_sibling_niche` | 0.08 |
| `tertiary_industry` | 0.06 |
| `geographic_alignment` | 0.04 |
| `life_stage_signal` | 0.04 |
| `values_aligned` | 0.05 |
| `complementary_to_exclusivity` | 0.05 |
| `graph_expansion_2nd_degree` | 0.03 |

Scores then capped at 1.0 (multi-source brands hit the ceiling fast — by design).

### Tier assignment

| Tier | Score range | Note |
|---|---|---|
| `re-engage` | any score with `previous_brand_reengage` source | Always grouped separately in UI |
| `primary` | ≥ 0.50 | "Reach out first" list |
| `secondary` | 0.25–0.50 | "Reach out next" list |
| `tertiary` | 0.10–0.25 | Long tail; review and cherry-pick |
| omit | < 0.10 | Drop from default view |

### Policy filters (applied last)

Re-applies the policy layer from `recommendation_algorithm.md`:
- Brand's `industry_id` in `talent.brand_preferences.blocked_industries` → exclude, list in `blocked[]` with reason.
- Brand's `industry_id` matches an `active_exclusivity` window → exclude, list in `blocked[]`.
- Brand's `industry_id` is `sensitive: true` and not in `preferred_industries` → keep, attach `warning: sensitive_category` to the result.
- `previous_brands[].do_not_recontact == true` → exclude.

### Deduplication beyond simple name-matching

A brand can appear under multiple names (Lulu / Lululemon / Lululemon Athletica). Dedupe via:
1. Normalize name (lowercase, strip "Inc/Ltd/Plc/Athletica" suffixes, strip whitespace).
2. Match against `brand_industry_map.json` `aliases[]`.
3. If still ambiguous, prefer the canonical `name` field from `brand_industry_map.json`.

---

## Schedule

### Per-talent search runs

| Trigger | What runs |
|---|---|
| Talent profile saved/updated | Full re-run of all 14 searches; replace `data/brand_candidates/{talent_id}.json` |
| Monthly cron (1st of month) | Full re-run for every active talent; primarily catches: newly-eligible re-engagements (Search 1), newly-added similar talents enriched in the interim (Search 2), industry/affinity edits to JSON (Searches 5–9) |
| `data/brand_industry_map.json` changes (new brands added) | Re-run Searches 3, 4, 5, 6, 7 only (the searches that read brand_industry_map) — incremental, doesn't need full re-run |
| Manual trigger by user ("refresh candidates") | Full re-run on demand |

### Re-engagement (Search 1) — the headline scheduled job

- **Cadence:** monthly cron per talent, 1st of each month.
- **Logic:** scan `talent.previous_brands[]`. For each entry, compute `days_since = today - max(campaign_date, last_re_engagement_pitch_date)`.
- **Eligibility:** `days_since ≥ cool_down_days` (default 180; brand-level override allowed).
- **Surface:** any newly-eligible re-engagement gets `tier: "re-engage"` and weight 0.60 — it bubbles to the top of the candidate list automatically.
- **De-spam:** if a re-engagement pitch was already sent in the last cycle and got no response, increase the cool-down by 50% on the next iteration to avoid harassing brands. Track in `talent.previous_brands[].pitch_history[]`.

---

## Searches that need external data (future versions)

These would meaningfully extend coverage but require integrations beyond the current JSON. Prioritised by impact-vs-effort.

| # | Search | What it adds | External dependency | Priority |
|---|---|---|---|---|
| 15 | Brands **currently running creator campaigns** in talent's niche | Live signal: who has budget on the table this week | Scrape `#ad` / "Paid partnership" tags on IG/TikTok for creators in same niche + LLM extract brand names; OR Modash / HypeAuditor / Tribe Dynamics API | **HIGH** |
| 16 | **Recently funded** D2C brands in talent's industries | Pre-IPO/post-funding brands are the most likely to launch creator programs | Crunchbase API + filter by `industry_id` keywords | **HIGH** |
| 17 | Brands with **active affiliate programs** | Pre-qualified for creator deals; lower barrier to entry | ShareASale / Awin / Impact / Rakuten / LTK / ShopMy APIs | **HIGH** |
| 18 | Brands by **rate card tier compatibility** | Filters out brands too big/small for talent's actual price point | Per-brand `typical_campaign_tier` (needs enrichment) | **MEDIUM** |
| 19 | **Trade show exhibitors** in talent's category | Brands actively spending marketing budget in this vertical | Scraped exhibitor lists per show (Beautycon, Cosmoprof, FIBO, ISPO, etc.) | **MEDIUM** |
| 20 | **Retail accelerator alumni** in talent's category | Emerging brands at major retailers with marketing momentum | Target Accelerators, Sephora Accelerate, Macy's Holiday Marketplace, Whole Foods Local | **MEDIUM** |
| 21 | Brands with **recent influencer-agency appointments** | Strong signal that creator budget just landed | Adweek / Drum / PRWeek / Campaign press releases | **MEDIUM** |
| 22 | **Seasonal product launches** in talent's category | Time-sensitive briefs aligned to launch windows | PR Newswire / PRWeb feeds; LLM categorisation | **MEDIUM** |
| 23 | Brands on **creator marketplaces** | Brands self-listing = actively looking | Aspire / Grin / BrandSnob / Creator.co marketplace APIs | **MEDIUM** |
| 24 | **EMV / influencer-ROI top performers** in talent's category | Brands historically getting strong creator-ROI keep investing | HypeAuditor / Tribe Dynamics / CreatorIQ EMV reports | **LOW** |
| 25 | Brands whose **audience overlaps** with talent's audience (look-alike) | Cross-industry signal: "people who buy X also buy Y" | Resonate / Comscore / Nielsen-style audience-overlap data — expensive | **LOW** |
| 26 | Brands matching talent's **personal values commitments** (positive D&I, sustainability, etc.) | Authenticity-driven matching | ESG databases (Sustainalytics, MSCI ESG); manual curation | **LOW** |

---

## Structural moves that unlock more searches with no external API

Two pieces of one-time data work would meaningfully expand the in-house searches:

### A. Enrich `brand_industry_map.json` with brand metadata

Add five fields per brand (estimated 290 records × ~2 min each = ~10 hours of authoring, or 1 hour with AI-assisted bulk enrichment + review):

```jsonc
{
  "name": "Gymshark",
  "industry_id": "activewear",
  "aliases": ["gym shark"],
  "domain": "gymshark.com",
  // NEW FIELDS:
  "hq_country": "GB",                                            // ISO 3166-1 alpha-2
  "sells_in_countries": ["GB","US","AU","DE","FR","CA"],         // primary markets
  "company_stage": "private_growth",                             // enum: bootstrapped | seed | series_a-d | private_growth | public | subsidiary
  "typical_campaign_tier": "mid",                                // enum: nano | micro | mid | macro | premium  (matches creator follower tiers)
  "creator_program_presence": ["aspire","direct"]                // observed channels
}
```

**Unlocks:**
- Search 10 (geographic alignment) — sharper than TLD heuristic.
- Search 11 (life stage) — `target_audience_summary` could be added too.
- Search 18 (rate card tier matching).
- Search 23 (creator marketplace presence — partial — needs marketplace API for live data but presence flag is a good proxy).

### B. Add `data/brand_competitors.json`

A focused brand-to-brand competitor graph for the top ~100–200 well-known brands. JSON shape:

```jsonc
{
  "version": "1.0.0",
  "competitors": {
    "Gymshark": ["Lululemon", "Alo Yoga", "Sweaty Betty", "Vuori", "Outdoor Voices"],
    "Tesla": ["Rivian", "Polestar", "Lucid", "BYD", "Mercedes-EQ"],
    "Allbirds": ["Veja", "Cariuma", "Rothy's", "Atoms"]
  }
}
```

**Why curate vs derive from industry_id:** two brands in the same `industry_id` aren't always direct competitors. A bespoke graph captures "Lululemon and Gymshark are direct" vs "Lululemon and a generic activewear brand are not really substitutable". Improves Search 3 quality dramatically.

**Scope:** start with the top brands by frequency of appearance in `brand_industry_map.json` aliases + the top brands in `previous_brands[]` across all talents. ~200 records is enough to cover the high-value comparisons.

---

## Open questions for v0.2

1. **Search-result freshness.** Should candidate lists carry a freshness TTL per source? E.g. `primary_industry` matches are valid 30 days; `demographic_bridge` matches re-evaluate weekly if the talent's audience demos shift.
2. **Multi-talent cross-pollination.** If we manage 10 talents, brand candidates surface across them — that's a roster-level dashboard view, not just per-talent. Should we expose "brands in our roster's collective candidate pool ranked by total fit" as a separate view?
3. **Negative learning loop.** When a brand candidate gets rejected ("talent passed on this") or pitched-and-failed, do we down-weight similar brands going forward? Requires a feedback capture mechanism in the outreach flow.
4. **Per-search confidence calibration.** All 14 searches currently use fixed weights. Once we have outcome data (which sources actually produced closed deals), tune weights against real conversion rates rather than guessing.
5. **Brand-level "next action hint".** Today `next_action_hint` is a free-text string. Could be templated: cold-outreach copy / re-engagement copy / marketplace-apply / agency-pitch / agency-of-record contact / etc. Tightly couples to the outreach phase.
6. **Pitch readiness scoring.** Beyond fit, score each candidate on "how ready are we to pitch?" — do we have the brand's marketing contact? do we have a media kit tailored to the brand's category? — and surface gaps in the dashboard.
7. **Multi-niche talent edge cases.** A talent with 5+ niches risks search 5 returning a flood of low-confidence primaries. Cap per-niche contribution or boost cross-niche overlaps?
8. **De-dup against blocked.** A brand flagged as blocked might still surface through 3 different searches. Confirm we exclude them once and don't re-surface elsewhere in the UI.
