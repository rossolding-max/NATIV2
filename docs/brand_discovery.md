# Brand Discovery — Long-List Generation

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the system that takes a complete talent profile and produces a ranked long-list of every brand worth pitching.

Reads: `talents/{id}.json` + the full `data/` directory (including the enriched `brand_industry_map.json` and `brand_competitors.json`) + (eventually) external APIs.
Writes: `data/brand_candidates/{talent_id}.json` (one per talent, rebuilt on schedule + on profile change).

Pairs with:
- `docs/recommendation_algorithm.md` — runs first on the talent profile and ranks **industries**; the recommended industries feed Searches 5–9 here.
- `docs/onboarding_workflow.md` — produces the talent profile this doc reads. Step 9B of onboarding triggers the first Brand Discovery run automatically.
- `docs/brand_enrichment_workflow.md` — Searches 15 and 16 surface novel brands and call this pipeline to enrich them before adding to the candidates file.
- `docs/contact_enrichment_workflow.md` (Phase 3a) — when a brand surfaces here at `tier: primary` AND `qualification.tier ∈ [qualified, speculative]`, the contact enrichment pipeline kicks off automatically to find named contacts at that brand. The contacts file (`data/brand_contacts/{brand_id}.json`) becomes the input for Phase 3b outreach.
- `docs/vendor_roadmap.md` — the external services these searches use (Exa confirmed; `last30days` skill via its own sub-services).

---

## Goal

Produce an **exhaustive** ranked list of brand-deal candidates for a given talent — not just the obvious primary-industry matches, but the long tail of brands that are genuinely reachable. The list is built by running **many independent searches in parallel** and merging the results. A brand that surfaces from multiple searches is a higher-confidence candidate than one that surfaces from one — the count itself is the ranking signal.

---

## Output: schema, storage, merge semantics

**Schema:** [`schemas/brand_candidates.schema.json`](../schemas/brand_candidates.schema.json) (JSON Schema Draft 2020-12). This is the authoritative shape of every candidates file. Validate on every write.

**Folder layout:**
```
data/brand_candidates/             ← gitignored (generated artifact)
├── current/
│   ├── jane-doe.json              ← latest view per talent (rewritten on each run)
│   └── ...
└── runs/
    ├── jane-doe/
    │   ├── run_2026-05-26.json    ← immutable monthly snapshots
    │   ├── run_2026-06-01.json    ← (kept indefinitely — needed for rising-delta /
    │   └── run_2026-07-01.json    ←  mention-velocity enhancements; storage tiny)
    └── ...
```

The folder is gitignored — these are app-generated, rewritten monthly, and would create unmanageable commit churn. The schema lives in the repo; the generated data does not.

**Merge semantics — preserving workflow state across re-runs.**
Each candidate has two halves:
- **Discovery-output fields** (`score`, `tier`, `sources`, `niche_signals`, `brand_snapshot`, `qualification`, `warnings`, `next_action_hint`, `found_in_searches`, `last_seen_in_searches`, `last_surfaced_at`) — **rebuilt every run**.
- **Workflow-state fields** (`status`, `assigned_to`, `user_notes`, `pitch_history`, `first_surfaced_at`) — **preserved across runs**.

On each run, the orchestrator:
1. Loads the previous `current/{talent_id}.json` if it exists; indexes existing candidates by `brand_id`.
2. Runs all 16 searches → produces fresh candidate records.
3. **Merge per candidate by `brand_id`:**
   - **Exists in previous + present in this run** → carry forward workflow-state fields; overwrite discovery-output fields.
   - **New brand** → `status: "new"`, `first_surfaced_at: now`.
   - **Existed in previous but not in this run** → keep on file, set `last_seen_in_searches: []` and add `warning: stale_in_pipeline`. (Useful signal — a brand that's dropped out of discovery may indicate the relationship has cooled or our affinity edges have drifted.)
4. Write `current/{talent_id}.json` and an immutable snapshot under `runs/{talent_id}/run_{date}.json`.

This guarantees a user-set `status: "shortlisted"` survives next month's discovery run intact.

## Output shape

The full canonical example below conforms to `schemas/brand_candidates.schema.json`. Original file path:

`data/brand_candidates/current/{talent_id}.json`:

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

## The 16 searches (runnable today on current JSON)

Each search is independent; all run in parallel; results merge by brand name + industry.

### Group A — Re-engagement (highest conversion likelihood)

#### Search 1 — Previous brands eligible for re-engagement
**Reads:** `data/brand_deals/{talent_id}.json` (richer record, populated per Phase 1.5 `docs/brand_deals_workflow.md`); falls back to `talent.previous_brands[].campaign_date` for legacy entries without a `deal_id`.
**Logic:** for each deal where `today ≥ renewal_eligibility_date` AND `do_not_recontact == false`, surface as a re-engagement candidate.
**Output tag:** `tier: "re-engage"`. Weight 0.60 — highest of any source because warm contacts convert far better than cold.
**Schedule:** monthly cron job per talent. Surfaces newly-eligible re-engagements as their cool-down elapses.
**Cool-down logic (deal-record-driven):**
- `renewal_eligibility_date` is computed by the orchestrator: `deal.ended_at + (deal.cool_down_override_days OR 180_days_default)`. Re-computed whenever `ended_at` or `cool_down_override_days` changes.
- Per-deal override: a brand might explicitly say "come back in March" — set `cool_down_override_days` to the gap in days; orchestrator does the math.
- Permanent block: `deal.do_not_recontact == true` (set after a soured deal) → never re-surface.
- **Outcome-based downrank:** deals with `outcome ∈ ["unfulfilled", "underperformed"]` are downranked or filtered (configurable per talent) — re-engaging a brand we underperformed for usually fails.
- **Anti-spam de-spam:** if `deal.last_re_engagement_pitch_date` shows we pitched recently with no response, extend the cool-down by 50% on the next iteration. The orchestrator updates `last_re_engagement_pitch_date` whenever a re-engagement pitch is sent — closing the loop.
**Per-deal KPI context:** when a deal is surfaced for re-engagement, its KPIs become available citation material for the outreach email (see `docs/outreach_workflow.md` Step C). Email generator can compose pitches like "Following our Q4 campaign — we hit 1.24M reach and $38k attributed sales. New angle for Q2?" rather than just "Hi again."

### Group B — Network expansion

#### Search 2 — Brands similar talents have worked with
**Reads:** `talent.similar_talent[].previous_brands[]` (populated by AI research in onboarding Step 9).
**Logic:** flatten all brands from all similar talents; for each brand, count how many similar talents worked with it. A brand 3+ similar talents have worked with is a very strong signal.
**Edge:** filter out brands already in `talent.previous_brands` (those are covered by search 1).

#### Search 3 — Direct competitors of talent's previous brands
**Reads:** `talent.previous_brands[].brand` (name) + `data/brand_competitors.json` + `data/brand_industry_map.json`.
**Logic:**
1. **Primary path:** for each brand in the talent's history, look it up in `brand_competitors.json` → return its curated competitor set directly. Cleanest signal; ~290 named brands have curated competitor sets.
2. **Fallback path:** if a brand isn't in `brand_competitors.json` (or has fewer than 3 competitors listed), fall back to same-`industry_id` lookup in `brand_industry_map.json`.
Filter out the talent's own previous brands (already covered by Search 1).
**Why the graph beats industry-only:** two brands in the same `industry_id` aren't always direct competitors (Tesla and a generic auto-OEM share `ev-brands` but aren't substitutable). The curated graph captures the actual competitive set per the marketing-and-positioning view.

#### Search 4 — Direct competitors of similar talents' brands
**Reads:** Search 2 output + `data/brand_competitors.json` (primary) + `data/brand_industry_map.json` (fallback).
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
**Reads:** `talent.audience_demographics.top_countries[]` + `data/brand_industry_map.json` `hq_country` + `sells_in_countries` fields (now enriched on all 290 brands).
**Logic:**
1. Take talent's top 3 audience countries.
2. **Boost** any candidate brand whose `sells_in_countries` includes at least one of them, or whose `hq_country` matches one.
3. **Discover** mode: for each top audience country, scan `brand_industry_map.json` for brands that sell there (and are in industries already surfaced by Searches 5–9) but haven't appeared in any other search yet — these are geo-relevant tail candidates.
**Edge:** `sells_in_countries: "global"` brands match every audience country (the literal string acts as a wildcard) but get a smaller boost than country-specific matches, since "global" is weaker signal than explicit market presence.

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
**Reads:** `talent.previous_brands[]` → competitor brands via `data/brand_competitors.json` (Search 3 output) → cross-reference with `talent.similar_talent[].previous_brands[]` and other talents in our system (if multi-talent roster).
**Logic:** find creators who worked with the talent's previous brands' competitors → look at *those* creators' brand history → identify brands that appear repeatedly. These are brands clustered around the same competitive set.
**Why it matters:** surfaces cross-industry patterns the industry filter misses. If Tesla buyers also frequently engage with premium audio brands, a creator who's worked with Tesla should see Sennheiser surfaced even though `ev-brands` and `audio-equipment` aren't strongly linked in the affinity matrix.
**Limit:** depends on roster size. With 1 talent and few similar talents, this is thin. Grows valuable as the roster + similar-talent database grows.

### Group G — Momentum signals (search-driven, no API yet)

#### Search 15 — Recently funded / newly visible brands in the talent's industries
**Reads:** `talent.content_niches[]` → primary/secondary industries → semantic web search via **Exa** (confirmed v0.1 provider; see `docs/vendor_roadmap.md`).
**Logic:**
1. For each of the talent's top industries, run targeted Exa searches:
   - Neural queries via `/search`: `"<industry> D2C brand Series A 2026"`, `"<industry> launched startup"`, `"<industry> trending brand to watch"`.
   - For each high-signal result, optionally use Exa's `/findSimilar` to pull lookalike pages and broaden recall.
   - Use `/contents` to extract structured page text for the LLM extractor.
2. LLM (Claude Haiku) extracts brand names from the page contents and classifies each against `data/industries.json`.
3. Each new brand gets:
   - Added to `data/brand_industry_map.json` (writeback) with `company_stage` inferred from the funding signal where possible (e.g. "Series A").
   - Surfaced as a candidate with the `recently_funded` source tag.
**Why it matters:** newly-funded / newly-visible D2C brands are the most likely to be launching creator programs and have fresh budget to spend. They're also the most likely to be MISSING from a static seed file. This search is the discovery loop that keeps `brand_industry_map.json` growing.
**Quality control:** the LLM tags each extracted brand with a confidence + source URL. Low-confidence extractions are surfaced for user review before they're committed to `brand_industry_map.json`.
**Why Exa over alternatives:** purpose-built for AI-agent workflows; neural + keyword hybrid; structured content extraction; `findSimilar` endpoint is uniquely useful for broadening discovery from one seed page. Alternatives (Brave, Tavily, SerpAPI) noted in `docs/vendor_roadmap.md` as fallbacks if Exa free tier becomes constraining.
**Caveats vs API version (#17 in future-versions):**
- **No structured filtering** by funding stage / amount / date (search returns whatever Exa surfaces semantically).
- **Freshness depends on Exa's crawl freshness** — typically within days, but very-recent announcements may lag.
- **Search quotas** apply per orchestrator run; budget appropriately within Exa's free tier or paid plan.
- **De-dup is critical** — the same brand will surface from many queries; merge by normalized name.

**Future enhancement — Crunchbase API integration (deferred):**
Once integrated, replaces the LLM-search step with structured Crunchbase queries by `industry_keywords + funded_after + stage_in [seed, series_a-c]`. Gives precise filters, freshness within 24h, and structured metadata (founding date, total raised, last round size) that the search-only path can only approximate. Tracked in `External-data future searches § #17` below.

#### Search 16 — Trending / rising brands via the `last30days` skill
**Reads:** `talent.content_niches[]` + derived top industries via `niche_industry_affinity.json` + the [`last30days` skill](https://github.com/mvanhorn/last30days-skill).

**What the skill does (summary):** multi-source social research — Reddit, X, YouTube, TikTok, Hacker News, Bluesky, GitHub, Polymarket, plus Brave/Perplexity web search — with entity resolution (figures out *where* to look first), parallel multi-query expansion, engagement-weighted scoring (upvotes, likes, views), cross-platform clustering with deduplication, and a per-author cap (max 3 items per voice) so no single account dominates. Outputs a markdown synthesis with inline citations and source attribution.

**Logic:**
1. For each of the talent's top 3–5 niches (and their primary industries), invoke `last30days` with a small fan-out of trending-brand queries:
   - `"new <industry> brands"`
   - `"trending <niche> brand"`
   - `"viral <industry> launch"`
   - `"<industry> brands to watch"`
   - `"<niche> creator partnership"`
2. The skill returns multi-source synthesis with engagement-weighted, deduplicated clusters of brand mentions.
3. LLM post-processor extracts brand names from the synthesis, capturing per brand:
   - Canonical brand name
   - Source platforms with engagement metrics (e.g. `Reddit r/MaleFashionAdvice 320 upvotes, TikTok 1.2M views, HN 84 comments`)
   - **Engagement signal strength**: `low` (1 source / modest engagement) → `medium` (2–3 sources / decent engagement) → `high` (4+ sources / viral metrics)
   - Source URLs and the saved synthesis file path
4. Each extracted brand becomes a candidate with `trending_30d` source tag; weight scales with engagement signal strength (low 0.10 / medium 0.15 / high 0.20).
5. **Writeback:** brands not yet in `brand_industry_map.json` get AI-classified into an industry and added — same growth loop as Search 15. Synthesis file path stored on the candidate for traceability.

**Why it matters:** unlike Search 15 (funding-driven; biased toward brands with PR teams), Search 16 surfaces brands generating organic social momentum — arguably the strongest creator-marketing signal available. A brand with 4 Reddit threads + viral TikToks + HN discussion is the one creators should be pitching *this month*, regardless of whether they've raised institutional capital. Catches creator-economy momentum that none of the other 15 searches will see.

**Cadence:** monthly cron job per talent, naturally aligned to the skill's 30-day rolling window. Default schedule: 1st of each month, batch all active talents. Results merge into the standard `brand_candidates/{talent_id}.json` output with `tier` and `score` computed alongside every other search.

**Cost/quota:**
- Reddit / HN / Polymarket / GitHub / Bluesky / YouTube (via `yt-dlp`): free.
- X / Brave Search: free tiers (Brave: 2,000 queries/month).
- TikTok / Instagram / Threads / Pinterest: requires `SCRAPECREATORS_API_KEY` (100 free credits/month, then pay-as-you-go).
- Perplexity Sonar: optional, requires `OPENROUTER_API_KEY` (paid).
- **Budget per talent per run:** ~3–5 niches × ~5 queries ≈ 15–25 queries. For a 50-talent roster: ~1,000 queries/month, comfortably within Brave's free tier. ScrapeCreators credits should be conserved for the highest-signal niches (e.g. niches where TikTok is the dominant platform — beauty, fashion, fitness).

**Quality control:**
- LLM brand extractions tagged with confidence; low-confidence brands flagged for user review before writeback to `brand_industry_map.json`.
- Per-author cap (3 items per voice) is built into the skill — prevents one viral creator's stack of mentions inflating the signal.
- Brand name disambiguation: same brand may be referenced across sources with slight variants (e.g. "Liquid Death" vs "@liquiddeath" vs "liquiddeath.com"). LLM normalises before merge.

**Future enhancement (deferred, no new tools needed — just persistence):**
- **Rising delta:** compare this month's extracted brand list against last month's; brands *new to the trending list this run* get an additional `newly_trending` boost. Requires keeping the last N months of run output.
- **Mention velocity:** track each brand's appearance across consecutive monthly runs → distinguish brands sustaining momentum (3+ months on the trending list) from one-hit-wonder spikes. Sustained signal is far more valuable for creator partnerships than a one-week viral moment.

---

## Scoring & deduplication

### Merge

After all 16 searches run, merge by `(brand, industry_id)` tuple. A brand surfacing from multiple searches accumulates `sources[]` entries.

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
| `recently_funded` | 0.10–0.15 (scales with stage signal strength) |
| `trending_30d` | 0.10–0.20 (low/medium/high engagement signal via last30days skill) |
| `preferred_industry` | 0.10 |
| `competitor_of_similar_talent` | 0.10 |
| `parent_sibling_niche` | 0.08 |
| `tertiary_industry` | 0.06 |
| `geographic_alignment` | 0.04–0.08 (higher if `hq_country` match; lower if `sells_in_countries: "global"`) |
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

### Qualification filtering (applied before policy)

Filters out brands unlikely to be active creator-marketing buyers — keeps the list focused on candidates that can plausibly convert. Every candidate carries a `qualification` block with a `score` (0–1), `tier` (`qualified` / `speculative` / `unqualified`), and a `signals[]` log of positive and negative contributions.

**Signals contributing to qualification score:**

| Signal | Direction | Typical weight | Source |
|---|---|---|---|
| `active_creator_program` | + | 0.30 | `brand_industry_map.creator_program_presence` non-empty |
| `macro_or_premium_campaign_tier` | + | 0.20 | `typical_campaign_tier` in `[macro, premium]` |
| `mid_campaign_tier` | + | 0.10 | `typical_campaign_tier == "mid"` |
| `established_company` | + | 0.10 | `company_stage` in `[public, private_growth, subsidiary]` |
| `subsidiary_of_major_parent` | + | 0.05 | `company_stage == "subsidiary"` (known parent has marketing budget) |
| `recent_funding_round` | + | 0.10 | Brand surfaced via Search 15 with funding signal |
| `active_paid_partnerships_observed` | + | 0.15 | Last30days (Search 16) or external `#ad` scrape shows recent creator deals |
| `high_emv_in_category` | + | 0.20 | Future: Tribe Dynamics EMV data once integrated |
| `high_own_brand_follower_count` | + | 0.05 | Brand's own social account ≥ 100k followers (marketing-active proxy) |
| `micro_or_nano_campaign_tier` | − | −0.15 | Brand budgets too small to plausibly pay this talent's rate |
| `bootstrapped_or_early_stage` | − | −0.10 | `company_stage` in `[bootstrapped, seed]` |
| `low_own_brand_follower_count` | − | −0.10 | Brand's own IG/TT < 10k followers (rarely runs paid creator deals) |
| `no_creator_partnerships_observed` | − | −0.05 | No prior creator activity surfaced in any signal source |
| `b2b_vertical` | − | −0.20 | Industry is B2B-only (`consulting`, `accounting`, `legal-services`, `professional-services`, etc.) |
| `sensitive_vertical_warning` | − | varies | Sensitive industry without talent opt-in |

**Tier and filtering:**
- Score `≥ 0.60` → `qualified` (always shown)
- Score `0.30 – 0.60` → `speculative` (shown; UI may collapse by default)
- Score `< 0.30` → `unqualified` → `qualification_filtered: true` (hidden from default view; user can reveal)
- Threshold is configurable per talent (e.g. agency users handling enterprise brands may want lower threshold to surface B2B candidates the default rules suppress).

**Why this matters:** Without a qualification floor, the long-list is flooded with brands that have no realistic chance of running a creator campaign (e.g. a B2B consultancy that surfaced because its IAB Purchase Intent segments overlap with the talent's demographic profile). The qualification filter is what makes "exhaustive" useful rather than overwhelming.

### Policy filters (applied last)

Re-applies the policy layer from `recommendation_algorithm.md`:
- Brand's `industry_id` in `talent.brand_preferences.blocked_industries` → exclude, list in `blocked[]` with reason.
- Brand's `industry_id` matches an `active_exclusivity` window → exclude, list in `blocked[]`.
- Brand's `industry_id` is `sensitive: true` and not in `preferred_industries` → keep, attach `warning: sensitive_category` to the result.
- `previous_brands[].do_not_recontact == true` → exclude.
- `qualification_filtered == true` → kept in file but hidden from default view (see Qualification filtering above).

### Deduplication beyond simple name-matching

A brand can appear under multiple names (Lulu / Lululemon / Lululemon Athletica). Dedupe via:
1. Normalize name (lowercase, strip "Inc/Ltd/Plc/Athletica" suffixes, strip whitespace).
2. Match against `brand_industry_map.json` `aliases[]`.
3. If still ambiguous, prefer the canonical `name` field from `brand_industry_map.json`.

---

## brand_candidates.candidates[].status — sync discipline (GAP-06 fix)

`brand_candidates.candidates[].status` is a denormalised mirror of canonical state held in `pitch_enrollment` + `deal`. Values like `pitched / responded / negotiating / closed_won / closed_lost` come from downstream phases — Brand Discovery itself only writes `surfaced / qualified` initially.

**Sync requirement:** the denormalised status MUST stay in sync with canonical state, otherwise the UI surfaces stale labels.

**Sync source-of-truth per status:**

| Candidate status | Canonical source | Trigger event for sync |
|---|---|---|
| `surfaced` | (initial discovery write) | discovery_run write |
| `qualified` | `brand_candidate.qualification.tier ∈ [qualified, speculative]` | qualification scoring within discovery_run |
| `pitched` | `pitch_enrollment.enrollment_state ∈ [active, paused]` | pitch_enrollment creation |
| `responded` | `pitch_enrollment.outcomeClassification.outcome != null` | reply classification webhook |
| `negotiating` | `deal.stage ∈ [LEAD, PROPOSAL, CONTRACT] AND deal.originating_enrollment_id != null` | deal creation + state transitions |
| `closed_won` | `deal.stage = archived AND deal.is_won = true` | auto-archive fire |
| `closed_lost` | `deal.stage IN (lost terminal states) AND deal.is_won = false` | deal substage transition to terminal-lost |
| `dnc` | `brand_contact.contacts[].do_not_contact = true` (any contact for this brand) | brand_contact update webhook or manual flip |

**Implementation requirement (project plan M9 + M10):** a Celery task `sync_brand_candidate_status` runs on every:
- `pitch_enrollment` state transition (create / pause / resume / classify-reply / terminate)
- `deal` substage transition (any transition)
- `brand_contact.do_not_contact` flip

The task identifies the affected `brand_candidate` row by `(talent_id, brand_id)` lookup + writes the highest-priority status per the table above (e.g. closed_won wins over negotiating wins over responded wins over pitched wins over qualified wins over surfaced).

**Backfill:** on first deployment, run a one-shot sync over all existing brand_candidates to set status from current canonical state.

**Failure mode if skipped:** UI shows stale "pitched" status on brands that have actually won + archived — confusing for agents reviewing the discovery pipeline. Detectable + fixable via re-run of the sync task.

---

## Schedule

### Per-talent search runs

| Trigger | What runs |
|---|---|
| Talent profile saved/updated | Full re-run of all 16 searches; replace `data/brand_candidates/current/{talent_id}.json` |
| Monthly cron (1st of month) | Full re-run for every active talent; primarily catches: newly-eligible re-engagements (Search 1), newly-added similar talents enriched in the interim (Search 2), industry/affinity edits to JSON (Searches 5–9), **newly-funded brands via web search (Search 15), and rising/trending brands surfaced by the `last30days` skill (Search 16) over the past 30-day window** |
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

These would meaningfully extend coverage but require integrations beyond the current JSON. Prioritised by impact-vs-effort. Searches 15 (web-search-driven funding signal) and 16 (last30days social-momentum signal) were both upgraded to in-scope. The API-backed enhancement of Search 15 is #17 below.

| # | Search | What it adds | External dependency | Priority |
|---|---|---|---|---|
| 17 | **API-backed enhancement of Search 15** (recently funded brands with structured metadata) | Precise filters by funding stage / round / date; freshness within 24h; structured `total_raised`, `last_round_size` | Crunchbase API + filter by `industry_id` keywords | **HIGH** |
| 18 | Brands **currently running creator campaigns** in talent's niche | Live signal: who has budget on the table this week (overlaps with last30days but more targeted at paid-partnership detection specifically) | Scrape `#ad` / "Paid partnership" tags on IG/TikTok for creators in same niche + LLM extract brand names; OR Modash / HypeAuditor / Tribe Dynamics API | **HIGH** |
| 19 | Brands with **active affiliate programs** | Pre-qualified for creator deals; lower barrier to entry | ShareASale / Awin / Impact / Rakuten / LTK / ShopMy APIs | **HIGH** |
| 20 | Brands by **rate card tier compatibility** (live signal) | Sharper than the static `typical_campaign_tier` field — adds real-time budget signal from actual recent campaign fees | Aggregated creator-economy data (CreatorIQ / Aspire ledger / paid-post fee aggregators) | **MEDIUM** |
| 21 | **Trade show exhibitors** in talent's category | Brands actively spending marketing budget in this vertical | Scraped exhibitor lists per show (Beautycon, Cosmoprof, FIBO, ISPO, etc.) | **MEDIUM** |
| 22 | **Retail accelerator alumni** in talent's category | Emerging brands at major retailers with marketing momentum | Target Accelerators, Sephora Accelerate, Macy's Holiday Marketplace, Whole Foods Local | **MEDIUM** |
| 23 | Brands with **recent influencer-agency appointments** | Strong signal that creator budget just landed | Adweek / Drum / PRWeek / Campaign press releases | **MEDIUM** |
| 24 | **Seasonal product launches** in talent's category | Time-sensitive briefs aligned to launch windows | PR Newswire / PRWeb feeds; LLM categorisation | **MEDIUM** |
| 25 | Brands on **creator marketplaces** | Brands self-listing = actively looking | Aspire / Grin / BrandSnob / Creator.co marketplace APIs | **MEDIUM** |
| 26 | **EMV / influencer-ROI top performers** in talent's category | Brands historically getting strong creator-ROI keep investing | HypeAuditor / Tribe Dynamics / CreatorIQ EMV reports | **LOW** |
| 27 | Brands whose **audience overlaps** with talent's audience (look-alike) | Cross-industry signal: "people who buy X also buy Y" | Resonate / Comscore / Nielsen-style audience-overlap data — expensive | **LOW** |
| 28 | Brands matching talent's **personal values commitments** (positive D&I, sustainability, etc.) | Authenticity-driven matching beyond LLM evaluation | ESG databases (Sustainalytics, MSCI ESG); manual curation | **LOW** |

---

## Structural moves — completed in v0.1

Both structural moves originally flagged as "unlocks more searches" have shipped as part of this round and are now relied on by the searches above.

### A. `brand_industry_map.json` enriched ✅
All 290 brands carry five additional fields:
- `hq_country` — ISO 3166-1 alpha-2
- `sells_in_countries` — ISO list or the literal string `"global"`
- `company_stage` — `bootstrapped | seed | series_a..d | private_growth | public | subsidiary | state_owned | unknown`
- `typical_campaign_tier` — `nano | micro | mid | macro | premium | unknown` (matches creator follower tiers)
- `creator_program_presence` — observed channels: `direct | aspire | grin | ltk | shopmy | agency_of_record`

Honest-gaps policy: fields are present only when there's a confident value. Absence means "not yet enriched" — the app treats missing as unknown rather than assuming a default.

Reproducible via `scripts/enrich_brand_map.py` — re-run to update the enrichment.

**Unlocks:**
- Search 10 (geographic alignment) — uses `hq_country` + `sells_in_countries` directly.
- Search 11 (life stage) — informed by `typical_campaign_tier` proxy.
- Future scoring layer that filters by talent rate-card tier vs `typical_campaign_tier` compatibility (precursor to Search 19).

### B. `data/brand_competitors.json` shipped ✅
Curated brand-to-brand competitor graph. All 290 brands in `brand_industry_map.json` have a competitor set (1,241 directed competitor edges total). 33% of named competitors are themselves in `brand_industry_map.json`; the other 67% are "free-form" — known competitors that haven't yet been added to the map. The app resolves them on-demand via AI inference + writeback so the map grows over time.

JSON shape:
```jsonc
{
  "version": "1.0.0",
  "competitors": {
    "Gymshark": ["Lululemon", "Alo Yoga", "Sweaty Betty", "Vuori", "Outdoor Voices", "Under Armour"],
    "Tesla":    ["Rivian", "Polestar", "Lucid Motors", "BYD", "Mercedes-EQ", "Audi e-tron", "Ford Mustang Mach-E"]
  }
}
```

**Why curate vs derive from industry_id:** two brands in the same `industry_id` aren't always direct competitors. Tesla and a generic auto-OEM share `ev-brands` but aren't substitutable. The curated graph captures actual competitive sets per the marketing-and-positioning view.

**Unlocks:**
- Search 3 + 4 (direct-competitor lookup) use this as the primary source, falling back to same-`industry_id` only when the brand isn't in the graph.
- Search 14 (2nd-degree graph expansion) traverses the competitor graph directly.

---

## M7 implementation notes (shipped vs deferred)

M7 shipped the **Core 8** subset of the 16 searches plus the
qualification + policy-filter layers + the REST surface + the Celery
task that fires on `/activate`. **M7.1 added the remaining 8 searches**
on top: 6 deterministic graph-walk searches, the LLM-driven
values-aligned classifier, and the `last30days` trending skill
subprocess wrap.

**Shipped in M7 (Core 8):**

| # | Search | Why in Core 8 |
|---|---|---|
| 1 | Re-engagement (M6 cool-down + de-spam) | Highest-signal source (weight 0.60); reads the M6 brand_deal fields that landed last milestone |
| 3 | Competitors of previous brands | Deterministic graph walk via `data/brand_competitors.json`; instant signal |
| 5/6/7 | Primary / secondary / tertiary industries from niches | The discovery-volume floor; without these the candidate list is empty for new talent |
| 9 | Demographic bridge (IAB segment overlap) | Free lift once talent audience demos exist; deterministic |
| 10 | Geographic alignment | Free lift on top of industry matches; deterministic |
| 15 | Newly-funded via Exa + Claude | The only "discover net-new brands" path; expensive but unique value |

**Shipped in M7.1 (remaining 8):**

| # | Search | Weight | Notes |
|---|---|---|---|
| 2 | Similar-talent brands | 0.10–0.20 | Walks `talent.similar_talent[].previous_brands[]`; weight scales with mention count |
| 4 | Competitors of similar-talent brands | 0.10 | Composes Search 2 + Search 3 (one extra graph hop) |
| 8 | Parent + sibling niche walk | 0.08 | Extends Search 5/6/7 via the niche taxonomy parent/sibling pointers |
| 11 | Life-stage signal | 0.04 | Inline IAB-derived age-band → industry mapping (13-17 / 18-24 / 25-34 / 35-44 / 45-54 / 55+) |
| 12 | Complementary to active exclusivities | 0.05 | Positive-space inversion of the exclusivity block — adjacent industries the audience already responds to |
| 13 | Values-aligned (LLM classifier) | 0.05 | One Claude call per run; batches top 50 already-surfaced candidates against the talent's `values_aligned_themes` + `values_red_lines` |
| 14 | 2nd-degree competitor graph | 0.03 | Competitors-of-competitors; excludes 1st-hop set to avoid double-counting Search 3/4 |
| 16 | Trending via `last30days` skill | 0.06 | Subprocess to `~/.claude/skills/last30days/scripts/last30days.py`; mines Reddit + X items for known brand-name mentions; gated behind `settings.enable_last30days_discovery` since the skill needs OpenAI + xAI keys |

**Scoring** is `min(1.0, Σ source-weights)`. Tier is `re-engage` if any source tagged it (regardless of score), else `primary` ≥ 0.50, `secondary` ≥ 0.25, `tertiary` ≥ 0.10. Below 0.10 dropped.

**Qualification** is a separate 0-1 layer: signals (active creator program +0.30, macro tier +0.20, public/series-A funding +0.10, follower-count adjustments, b2b penalty -0.20). Default include threshold 0.30; per-talent override is a settings-level constant for v0.1.

**Policy filter** runs last: `blocked_industries` hard-block, active `exclusivities` industry-level block, `do_not_recontact` per brand-id block, sensitive industries kept-with-warning unless in `preferred_industries`.

**Output destination:** both `brand_candidate` rows (DB, indexed `(talent_id, brand_id)` unique; agent workflow state lives here) AND `data/brand_candidates/current/{talent_id}.json` (regenerated from DB) + immutable per-run snapshot at `data/brand_candidates/runs/{talent_id}/run_{ts}.json`. Snapshot writer preserves the workflow-state fields (status, assigned_to, user_notes, pitch_history, legal_entity_override, first_surfaced_at) across runs.

**Trigger:** M5's `/activate` Celery task body now runs the real orchestrator (replaces the stub). Manual rerun via `POST /api/v1/talents/{id}/brand-discovery/run`. No periodic beat schedule — re-discovery cron defers until there's a real cost budget.

**Cool-down + de-spam:** Search 1 reads M6's `ended_at` + `cool_down_override_days` (default 180) for eligibility, and extends the cool-down 50% if `last_re_engagement_pitch_date` is within the recency window (default 30 days). M9 outreach writes the pitch date when an outreach fires — closing the loop.

**Cost guard:** Search 15 fan-out caps at 3 industries × 2 queries × 5 results per run (≤30 Exa calls + 1 Claude call per industry). `settings.llm_budget_per_pack_usd` is a hard kill; M2 budget plumbing already enforces.

---

## Open questions for v0.2

1. **Search-result freshness.** Should candidate lists carry a freshness TTL per source? E.g. `primary_industry` matches are valid 30 days; `demographic_bridge` matches re-evaluate weekly if the talent's audience demos shift.
2. **Multi-talent cross-pollination.** If we manage 10 talents, brand candidates surface across them — that's a roster-level dashboard view, not just per-talent. Should we expose "brands in our roster's collective candidate pool ranked by total fit" as a separate view?
3. **Negative learning loop.** When a brand candidate gets rejected ("talent passed on this") or pitched-and-failed, do we down-weight similar brands going forward? Requires a feedback capture mechanism in the outreach flow.
4. **Per-search confidence calibration.** All 16 searches currently use fixed weights. Once we have outcome data (which sources actually produced closed deals), tune weights against real conversion rates rather than guessing.
5. **Brand-level "next action hint".** Today `next_action_hint` is a free-text string. Could be templated: cold-outreach copy / re-engagement copy / marketplace-apply / agency-pitch / agency-of-record contact / etc. Tightly couples to the outreach phase.
6. **Pitch readiness scoring.** Beyond fit, score each candidate on "how ready are we to pitch?" — do we have the brand's marketing contact? do we have a media kit tailored to the brand's category? — and surface gaps in the dashboard.
7. **Multi-niche talent edge cases.** A talent with 5+ niches risks search 5 returning a flood of low-confidence primaries. Cap per-niche contribution or boost cross-niche overlaps?
8. **De-dup against blocked.** A brand flagged as blocked might still surface through 3 different searches. Confirm we exclude them once and don't re-surface elsewhere in the UI.
