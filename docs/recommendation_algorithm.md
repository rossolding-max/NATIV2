# Recommendation Algorithm — Draft Spec

**Status:** Draft v0.1 — written before the app exists, to be the contract the app implements. Authored 2026-05-26.

## Goal

Given one talent profile (`talents/{id}.json`), produce a **ranked list of brand industries to target**, with explanations.

The output looks like:

```jsonc
[
  {
    "industry_id": "activewear",
    "score": 0.91,
    "tier": "primary",
    "warnings": [],
    "why": [
      { "source": "direct",   "weight": 0.60, "note": "Primary edge for niche `fitness`" },
      { "source": "bridge",   "weight": 0.25, "note": "Shared IAB Interest (Fitness, Healthy Living) + Demo (25-39 F)" },
      { "source": "preference", "weight": 0.06, "note": "In talent.brand_preferences.preferred_industries" }
    ]
  },
  ...
]
```

The algorithm has **five layers**, each contributing to the final score.

---

## Inputs

From `talents/{id}.json`:

| Field | Read for | Notes |
|---|---|---|
| `content_niches[]` | Layer 1 (direct), Layer 2 (bridge) | Look up `niche_industry_affinity.json` and `niche_audience_affinity.json` |
| `audience_demographics.age_bands` | Layer 2 (bridge) | IAB-aligned keys — direct lookup |
| `audience_demographics.gender_split` | Layer 2 (bridge) | Maps to IAB Female/Male/Other/Unknown |
| `previous_brands[]` | Layer 4 (preference) | Past industries are evidence of fit |
| `brand_preferences.preferred_industries[]` | Layer 4 (preference) | Score boost |
| `brand_preferences.blocked_industries[]` | Layer 5 (policy) | Hard exclude |
| `brand_preferences.active_exclusivities[]` | Layer 5 (policy) | Hard exclude until `ends_on` |
| `brand_preferences.values_red_lines[]` | Layer 5 (policy) | Soft warning (LLM-evaluated) |

From `data/`:

- `niches.json` — niche taxonomy + parent fallback
- `industries.json` — industry taxonomy + `sensitive` flag
- `niche_industry_affinity.json` — direct edges, 3-tier strength
- `niche_audience_affinity.json` — niche → IAB Interest + Purchase Intent + Demographic
- `industry_audience_affinity.json` — industry → IAB Interest + Purchase Intent + Demographic
- `iab_audience_taxonomy_v1.1.json` — segment lookups + parent chain

---

## Layer 1 — Direct affinity (60% weight)

The hand-authored ground-truth matrix. For each niche the talent has:

1. Look up the group in `niche_industry_affinity.json`.
2. Each `industry_id` in `primary[]` / `secondary[]` / `tertiary[]` gets a score:

| Tier | Score |
|---|---|
| `primary` | 1.0 |
| `secondary` | 0.6 |
| `tertiary` | 0.3 |

3. If the talent has multiple niches, **sum** scores per industry (capped at 1.0).
4. If a niche has no entry in `niche_industry_affinity.json`, walk up its `parent` chain in `niches.json` until an entry is found (parent fallback).
5. Apply per-edge `overrides[]` if present (carry edge-specific notes into `why[]`).

Layer-1 score per industry = sum of tier scores from each of the talent's niches, normalised to [0, 1] by dividing by `(number_of_niches × 1.0)`.

---

## Layer 2 — Bridged audience overlap (25% weight)

Uses the IAB Audience Taxonomy v1.1 as the bridge.

### Step A: Build the talent's IAB segment vector

- **Interest + Purchase Intent**: union of `interest_segments` and `purchase_intent_segments` from every niche group the talent has (via `niche_audience_affinity.json`).
- **Demographic**: derived from the talent's own `audience_demographics`:
  - `age_bands` — each key maps to its IAB segment ID (e.g. `"25-29"` → segment `5`). Bands with share ≥ 10% are added with that share as weight.
  - `gender_split` — primary gender (≥ 50% share) becomes IAB segment 49 (Female) / 50 (Male) / 51 (Other Gender).

### Step B: Score each candidate industry

For each industry (from `industry_audience_affinity.json`), compute weighted overlap with the talent's vector:

```
bridge_score(industry, talent) =
    1.0 * |shared_interest_segments|
  + 1.0 * |shared_purchase_intent_segments|
  + 0.5 * Σ(talent_age_share[i]) for i in shared_demographic_segments
  + 0.5 * gender_match_signal
```

Normalised by the size of the industry's segment vector (so industries with broad targeting don't dominate).

### Step C: Source weights in `why[]`

Each bridge match writes a `why` entry naming the matched segments. Example:

```jsonc
{ "source": "bridge", "weight": 0.25,
  "note": "Shared IAB Interest [408 Fitness, 406 Healthy Living], PI [1633 Exercise Equipment], Demo [25-29, 30-34, Female]" }
```

---

## Layer 3 — Past-deal signal (5% weight)

Industries that already appear in `talent.previous_brands[].industry_id` get a small boost — they're proven fits.

```
past_deal_score(industry, talent) = min(1.0, 0.5 * count_of_past_deals_in_industry)
```

---

## Layer 4 — Preference boost (10% weight)

```
if industry ∈ talent.brand_preferences.preferred_industries → +0.1
```

This is purely additive; it doesn't override the affinity signal, just nudges ranking.

---

## Layer 5 — Policy (hard filters and warnings)

Applied **after** layers 1-4 produce a base score:

| Condition | Effect |
|---|---|
| `industry ∈ talent.brand_preferences.blocked_industries` | **Hard exclude** from results |
| `industry == active_exclusivity.industry_id` AND `today ≤ ends_on` | **Hard exclude**; surface the active exclusivity in `warnings[]` |
| `industry.sensitive == true` AND not in `preferred_industries` | **Show with warning**: include in results but attach `{warning: "sensitive_category", details: ...}` to the result object. UI surfaces this. |
| `talent.brand_preferences.values_red_lines` contains a relevant phrase | Soft warning (LLM-evaluated for each candidate industry's typical messaging) |

The "sensitive: show with warning" policy is per [user decision 2026-05-26]: sensitive industries stay in the ranked list (so the talent sees the opportunity), but the UI shows a clear flag.

---

## Final score

```
score(industry | talent) =
    0.60 * layer1_direct_affinity
  + 0.25 * layer2_bridged_audience
  + 0.05 * layer3_past_deals
  + 0.10 * layer4_preference_boost
```

Then apply Layer 5 policy filters.

Tier assignment:
- `score ≥ 0.70` → display as `primary`
- `0.40 ≤ score < 0.70` → `secondary`
- `0.15 ≤ score < 0.40` → `tertiary`
- `< 0.15` → omit from default view

---

## Worked example: `talents/example-talent.json`

Talent has:
- `content_niches`: `[fitness, running, health-wellness, lifestyle]`
- `audience_demographics.age_bands`: 22% 21-24, 28% 25-29, 20% 30-34, 12% 35-39 (+ smaller bands)
- `audience_demographics.gender_split`: 71% female
- `previous_brands`: 1 entry in `sportswear`
- `brand_preferences.preferred_industries`: `[sportswear, activewear, supplements-brands, plant-based-food, travel-hospitality]`
- `brand_preferences.blocked_industries`: `[gambling, fast-fashion, tobacco-vape, alcohol-spirits, weight-management]`

**Layer 1 (direct):** `fitness → primary [activewear, sportswear, sports-nutrition, supplements-brands, fitness-equipment, gyms-studios, wearables]`. Combined with edges from `running`, `health-wellness`, `lifestyle`, the top direct candidates are `activewear`, `sportswear`, `supplements-brands`, `sports-nutrition`, `wearables`.

**Layer 2 (bridge):** talent vector = Interest [Fitness, Healthy Living, Wellness, Nutrition, Sports, Track], PI [Exercise Equipment, Gyms, Health & Fitness Apps, Personal Trainers, Athletics Equipment], Demo [Age 21-24, 25-29, 30-34, 35-39, Female]. Industries with highest IAB overlap: `activewear` (~9 shared segments), `gyms-studios` (~10), `sports-nutrition` (~8), `fitness-equipment` (~7).

**Layer 3:** `sportswear` gets a +0.5 past-deal boost.

**Layer 4:** `sportswear`, `activewear`, `supplements-brands`, `plant-based-food`, `travel-hospitality` each get +0.1 preference boost.

**Layer 5:** `gambling`, `fast-fashion`, `tobacco-vape`, `alcohol-spirits`, `weight-management` excluded. No active exclusivities. `mental-health-services` would have appeared via `health-wellness` direct edges and Layer 2 — included with a `sensitive` warning.

**Expected top-5 output:**

1. `activewear` — primary direct + max bridge + preference boost
2. `sportswear` — primary direct + past deal + preference boost
3. `supplements-brands` — primary direct + bridge + preference boost
4. `sports-nutrition` — primary direct + strong bridge
5. `gyms-studios` — secondary direct + strongest bridge

With warnings:
- `mental-health-services` — included, `warning: sensitive_category`

---

## Similar-talent inversion (back-deriving niches from brands)

A `similar_talent` record starts as `{name, handles, previous_brands}` — no niches authored. To populate `inferred_niches[]`:

For each `previous_brand` (with resolved `industry_id`):
1. Scan `niche_industry_affinity.json` for all groups where this `industry_id` appears in `primary[]` (weight 1.0), `secondary[]` (weight 0.6), or `tertiary[]` (weight 0.3).
2. Each matched niche accumulates a score across that similar-talent's brand list.
3. Final inference per niche:
   - Total weighted score ≥ 2.0 → `confidence: primary`
   - 1.0 ≤ score < 2.0 → `confidence: secondary`
   - 0.3 ≤ score < 1.0 → `confidence: tertiary`
   - Below 0.3 → omit

The `supporting_brands[]` field lists which brands contributed to each inference (so the UI can show "this niche is inferred because they worked with Gymshark, Myprotein, and On Running").

Set `research.status = "enriched"` and `last_researched_at` to the time of the run.

---

## Open questions / TODOs for v0.2

- **Geo affinity.** Talent country shares (e.g. 54% GB, 21% US) are currently unused. IAB has no country segments. Suggest a separate `geo_affinity` layer that uses brand HQ country + `talent.audience_demographics.top_countries` once we add a brand_country to `brand_industry_map.json`.
- **`audience.interests` as a slug-validated field.** Currently free-form. Could be slug-validated against either `niches.json` or IAB Interest IDs to add a fourth signal.
- **`values_red_lines` operationalisation.** Today a free-form list. Suggest LLM evaluation per candidate industry against each red line, with the LLM returning `{conflict: true|false, evidence: "..."}`.
- **Per-platform routing.** A talent with strong IG-fashion + strong TikTok-comedy audiences may want different industry recommendations per platform. Use `platforms[].audience_demographics_override` to compute per-platform scores, then merge.
- **Live-learn weights.** Once the app has accumulated real deal-closing data, the layer weights (60/25/5/10) should be tuned against actual conversion. Start hand-set, end ML-tuned.
- **Brand-level recommendations.** This spec ranks *industries*. Next phase ranks specific brands within an industry, using `brand_industry_map.json` + per-brand activity signals (recent campaign volume, RFP listings, etc.).
- **Confidence intervals.** Each layer should eventually carry confidence in addition to score (e.g. layer-1 direct is high confidence; layer-2 bridge with sparse demos is lower confidence).
