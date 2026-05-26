# Brand Deals Workflow (Phase 1.5)

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the rich brand-deal data layer — how it gets captured during onboarding, kept updated post-campaign, and integrated across every other phase of the system.

**Pairs with:**
- `schemas/brand_deal.schema.json` — the data contract.
- `docs/onboarding_workflow.md` — Step 3 (media pack) and Step 5 (questionnaire) are the primary capture surfaces for HISTORICAL deals at onboarding.
- `docs/deal_lifecycle_workflow.md` (Phase 4) — NEW deals close into this layer via auto-archive. Phase 4 deal's `close.archived_to_brand_deal_id` points here; this record's `archived_from_deal_id` points back.
- `docs/brand_discovery.md` — Search 1 (re-engagement) reads from this data.
- `docs/outreach_workflow.md` — the AI generation step uses this as citation material.
- `docs/contact_enrichment_workflow.md` — warm-intro identification via `main_brand_contact_id`.
- `data/pitch_angles.json` — 5 new angles + 3 enriched existing angles draw merge fields from deal records.

## Goal

For every talent in the roster, maintain a rich, verifiable record of every brand campaign — past, active, upcoming — with structured KPIs, commercials, audience match, qualitative outcome, and re-engagement metadata.

**Two use cases drive everything:**
1. **Citation material in pitches.** Outreach emails like "I drove 1.24M reach for Gymshark at a 7.4% ER — happy to walk through the audit" need real, sourced numbers behind them. The deal record is where those numbers live.
2. **Re-engagement timing.** Brand Discovery Search 1 needs to know when each past brand is eligible for a follow-on pitch — based on the campaign end date, any explicit brand instruction ("come back in March"), do-not-recontact flags, and whether we've already pitched a re-engagement recently.

**Honesty floor — same as elsewhere:** never fabricate KPIs. Every metric value has a `source` field (`platform_verified` / `brand_reported` / `third_party` / `calculated` / `self_reported` / `estimated`). Email generator strongly prefers higher-confidence sources when picking which figure to cite. Missing metrics are omitted; never null, never zero, never guessed.

## Where the data lives

`data/brand_deals/{talent_id}.json` — one file per talent. **Gitignored** — commercial KPIs and exact fees are sensitive; vendor data (Tribe Dynamics / HypeAuditor reports) is licensed.

The schema lives in the repo (`schemas/brand_deal.schema.json`); generated/captured data does not.

## Relationship to `talent.previous_brands[]`

Backwards-compatible: the lightweight `previous_brands[]` in `talents/{id}.json` stays as a fast index. Each entry can carry an optional `deal_id` pointing to the rich record:

```jsonc
// talents/jane-doe.json
{
  "previous_brands": [
    {
      "brand": "Gymshark",
      "industry_id": "activewear",
      "campaign_date": "2025-09-15",
      "deal_id": "deal_2025_gymshark_q4"   // ← optional FK
    }
  ]
}
```

When `deal_id` is set, the orchestrator reads the full record from `data/brand_deals/{talent_id}.json`. When absent (legacy or skeleton entries), it falls back to the inline fields.

This means existing talent files keep working unchanged. Adding rich deal data is additive.

## Three data sources (hybrid ingestion)

### A. Media pack extraction (onboarding Step 3)
**When:** during initial onboarding, when the talent uploads their media kit + past performance reports.
**What:** the multimodal LLM extracts deal records from PDFs / PPTX / Instagram Insights screenshots / brand invoices / case-study tearsheets in the upload.

Per deal extracted:
- `brand_name`, inferred `industry_id` via `brand_industry_map.json`
- `campaign_name`, `campaign_type` (LLM classifies into the 13-value enum)
- `started_at` / `ended_at` (dates parsed from headers / charts)
- `deliverables` (platform + format + count, parsed from rate-card-style sections)
- `kpis.*` extracted from charts and tables: reach, impressions, engagement_rate_pct, video_views, completion rate, saves, link_clicks, conversions where visible. Each tagged with `source` based on what's quoted (e.g. "Source: Instagram Insights" → `platform_verified`; "Brand reported" → `brand_reported`; otherwise `self_reported` with low confidence flagged for talent review)
- `performance_notes` from any qualitative summary text

Output goes to `data/brand_deals/{talent_id}.json` with `manually_verified_by_talent: false` — the talent reviews + confirms in Step 4 (reconciliation).

### B. Manual entry (onboarding Step 5 + ongoing post-campaign)
**When:** during onboarding for deals not in the media pack; ongoing whenever the talent marks a campaign complete in the UI.
**What:** guided form, one screen per deal:
- Identity fields (brand, name, dates) with type-ahead from `brand_industry_map.json`
- Campaign type picker (13 enum values)
- Deliverables — multi-row form (platform / format / count / optional URLs)
- KPI form — one input per metric; each has a "source" dropdown so the talent declares provenance honestly
- Outcome picker (6 values)
- Optional: case_study_url, performance_notes
- "Save + verify" button → sets `manually_verified_by_talent: true`

UX detail: when KPI source = `platform_verified`, the form prompts the talent to paste the screenshot URL or grant a one-time read of the relevant platform's insights API so we can pull the figure directly. This converts `self_reported` to `platform_verified` with one click.

### C. Platform API auto-pull (ongoing)
**When:** continuously, for talents who've connected their IG / TikTok / YouTube Insights via the OAuth tokens captured in onboarding Step 2.
**What:**
- The orchestrator knows which deliverable post URLs belong to which deals (from `deliverables[].post_urls`).
- A nightly job pulls fresh insights data for those posts: reach, impressions, engagement, video metrics.
- Updates `kpis.*` with `source: platform_verified`, `as_of: <today>`, `verified_at: <timestamp>`.
- Refreshes for ~30 days post-campaign (KPIs continue to grow from sharing/viral pickup; capture the peak).
- After 30 days, drops to monthly refresh for 12 months, then stops.

Caveats:
- Only works on platforms with OAuth read access.
- Some platforms (TikTok, certain IG accounts) require Business/Creator status.
- `brand_reported` KPIs (conversions, sales) can't be auto-refreshed — those require brand input.

## Deal lifecycle states

Each deal record has an implicit lifecycle, derived from `started_at` / `ended_at` / `outcome` / `kpis.*` populated state:

```
   drafted          ← talent flagged a deal coming up; pre-campaign
       │
       ▼
   live             ← started_at ≤ today ≤ ended_at; campaign is running
       │
       ▼
   completed        ← ended_at < today AND outcome = 'pending'; awaiting KPI input
       │
       ▼
   kpis_in          ← outcome ∈ {successful_renewed, successful, mixed, ...}
       │            ← AND at least 3 KPI fields populated
       ▼
   renewal_eligible ← today ≥ renewal_eligibility_date AND do_not_recontact == false
                      ← surfaced by Brand Discovery Search 1
```

The state isn't a stored field — it's computed from the data. The UI shows a status badge per deal.

## Integration with other phases

### → Brand Discovery Search 1 (re-engagement)

Today's Search 1 reads `talent.previous_brands[].campaign_date` and applies a 180-day cool-down. After this build:

| What | Source |
|---|---|
| Cool-down end date | `brand_deals[].renewal_eligibility_date` (computed from `ended_at` + `cool_down_override_days` or default 180) |
| Per-brand override | `brand_deals[].cool_down_override_days` — set when the brand explicitly said "come back in March" |
| Hard block | `brand_deals[].do_not_recontact == true` (set after soured deal) |
| Anti-spam | `brand_deals[].last_re_engagement_pitch_date` — if recent and no response, extend cool-down by 50% on next iteration |
| Outcome filter | Brands with `outcome == "unfulfilled"` or `outcome == "underperformed"` get downranked or filtered (configurable per talent) |

Search 1's de-spam logic explicitly updates `last_re_engagement_pitch_date` whenever a re-engagement pitch is sent, closing the loop.

### → Outreach AI generation (Step C of `outreach_workflow.md`)

The context loader pre-pends to every email-generation prompt:
- The talent's relevant `brand_deals[]` — filtered to deals in the same industry, same competitor set, or with the same brand if re-engaging
- Each deal contributes citation material to the LLM's "available facts" list
- LLM picks the most impressive metric available (preferring higher-confidence sources) for the email body

Example prompt fragment:
```
Citation material from talent's past deals (use to back up claims):

Deal: Gymshark (activewear, competitor of Alo Yoga per brand_competitors.json)
  - Reach: 1.24M (platform_verified, IG Insights, as of 2025-10-05)
  - Engagement rate: 7.4% (calculated)
  - Sales attributed: $38,000 (brand_reported)
  - Outcome: successful_renewed (Q1 2026)

When citing metrics, prefer platform_verified > brand_reported > third_party.
Always cite the deal's brand name + date.
```

### → Pitch angles (5 new + 3 enriched)

**New angles** (in `data/pitch_angles.json`):

| Angle | Strength | What fires it |
|---|---|---|
| `past_campaign_specific_metric` | 0.80 | A deal exists with notable KPIs (reach ≥ 100k, etc.) preferably in the same industry as the target |
| `past_campaign_brand_renewed` | 0.85 | A deal with `outcome == "successful_renewed"` |
| `past_campaign_high_conversion` | 0.85 | A deal with `kpis.conversions ≥ 100` or `kpis.sales_attributed_usd ≥ $5k` |
| `past_campaign_audience_overlap_proof` | 0.80 | A deal with `audience_overlap_with_brand_target_pct ≥ 65` |
| `past_campaign_beat_benchmark` | 0.90 | A deal with positive entries in `vs_industry_benchmark.*` — **schema present, fires zero times until v2 benchmarks ship** |

**Enriched existing angles** (no schema change; richer merge fields from deal records):

| Existing angle | Enrichment |
|---|---|
| `past_brand_direct_competitor` | Was: "I worked with {competitor_brand}." Now: "I drove {kpi_value} for {competitor_brand} — at {kpi_source_verification}." |
| `past_relationship_eligible` | Was: dates only. Now: "Following our Q4 2025 campaign — we hit 1.24M reach + $38k attributed sales. I have a new angle for Q2." |
| `case_study_available` | Pulls `case_study_url` directly from the deal record. |

### → Contact enrichment (warm-intro identification)

`brand_deals[].main_brand_contact_id` is an FK to a contact in `data/brand_contacts/`. When a deal exists with this field populated:
- That contact is auto-tagged `champion_for_talents: [talent_id]`
- When the same person changes brands (LinkedIn API picks up the move), we know we have a warm relationship at the new brand — surfaced as a `champion_internal_advocate` angle target there

This is the warm-relationship-mapping feature: past deal contacts follow their careers.

## KPI computation rules

Some KPIs can be derived from others. The orchestrator computes these automatically and stores with `source: calculated`:

| Derived metric | Formula |
|---|---|
| `cpm_usd` | `fee_usd / (impressions / 1000)` — if impressions present |
| `cpe_usd` | `fee_usd / engagement_total` — if engagement_total present |
| `cpv_usd` | `fee_usd / video_views` — if video_views present |
| `ctr_pct` | `link_clicks / impressions * 100` — if both present |
| `engagement_rate_pct` | `engagement_total / reach * 100` — only if not directly provided |

Calculated values are overwritten if a direct measurement becomes available later.

## Honesty-floor enforcement

Same posture as everywhere else in the system:

| Situation | Action |
|---|---|
| Source has a clear, dated value | Populate `kpis.{metric}` with `source` set |
| Multiple conflicting figures across sources | Prefer freshest from highest-confidence source; note discrepancy in `performance_notes` |
| No source found | **Omit the metric entirely.** No null, no zero, no guess |
| Self-reported only, no platform verification possible | Populate with `source: self_reported` — email generator will deprioritise these vs verified figures |
| Value clearly stale (>6 months since last update for an active campaign) | Use it but flag in UI for refresh |

The `manually_verified_by_talent` flag on the deal record indicates the talent has eyeballed and confirmed the data. Unverified records (AI-extracted from media pack but not yet talent-reviewed) get a lower weight when the email generator picks citation material.

## State machine

```
INGESTION SOURCES
    ┌─────────────────────┐
    │ Media pack          │ (onboarding Step 3)
    │ AI extraction       │
    └────────┬────────────┘
             │
    ┌────────▼────────────┐
    │ Manual form         │ (onboarding Step 5 + ongoing)
    │ talent enters       │
    └────────┬────────────┘
             │
    ┌────────▼────────────┐
    │ Platform API pull   │ (nightly cron for active deals;
    │ (auto-refresh KPIs) │  monthly for 30-day to 12-month window)
    └────────┬────────────┘
             │
             ▼
    ┌─────────────────────────────────────┐
    │ data/brand_deals/{talent_id}.json   │
    └────────┬────────────────────────────┘
             │
   ┌─────────┼─────────────┬─────────────────────┐
   │         │             │                     │
   ▼         ▼             ▼                     ▼
Brand     Outreach     Contact          Pitch angles
Discovery AI gen       enrichment       (5 new + 3 enriched)
Search 1  (citation    (warm-intro
(re-eng)  material)    flagging)
```

## Failure handling

| Failure | Behaviour |
|---|---|
| Media pack LLM extracts conflicting numbers on the same KPI | Use the figure with the most explicit source citation; note the conflict in `performance_notes`; flag for talent review |
| Platform API rate-limited | Retry with exponential backoff; queue for next day if persistent |
| Platform API returns no data for a post URL (post deleted) | Mark the deliverable URL as 404 in `deliverables[].post_urls`; don't refresh that post's KPIs anymore |
| Talent disputes an extracted figure | UI lets them edit + sets `manually_verified_by_talent: true` + `source: self_reported` (with the previously-extracted figure kept in record history) |
| Brand-reported figure exists but never refreshable | Captured once, flagged in UI as "brand-reported, not independently verifiable"; email generator notes this when citing |
| Deal record is missing `ended_at` (still active) | `renewal_eligibility_date` stays null; deal isn't surfaced by Search 1 |
| Schema validation fails on save | Surface inline errors; talent fixes before save |

## Open questions for v0.2

1. **Industry benchmarks file** — the big v2 deliverable that unlocks `past_campaign_beat_benchmark` (currently dormant). Source: a curated `data/industry_kpi_benchmarks.json` from Influencer Marketing Hub / HypeAuditor / Tribe Dynamics public reports. ~20 industries × 5 platforms × ~6 metrics = ~600 benchmark values to author.
2. **Brand-side reporting integration** — some brands provide formal post-campaign reports (Looker dashboards, custom PDFs). Worth a parser path that extracts conversions / sales_attributed directly from those.
3. **Multi-creator campaigns** — when 3 creators run the same campaign for a brand, today each creator has their own deal record. Worth modelling the campaign-level aggregate so the user can see "this brand spent $X total across N creators".
4. **EMV integration** — `kpis.emv_usd` is in the schema. Sourcing requires Tribe Dynamics / HypeAuditor (paid). v2 vendor decision.
5. **Audience-overlap measurement** — `audience_overlap_with_brand_target_pct` is currently a free input. Could be computed from IAB segment overlap if the brand publishes their target demographics. Worth a structured "brand target audience profile" addition to `brand_industry_map.json`.
6. **Renewal pipeline view** — UI surface that shows all deals approaching `renewal_eligibility_date` in the next 30 days, sorted by past-campaign success. Phase 3a/3b can pre-stage outreach for these.
7. **Manual override layer for AI extraction** — when the talent corrects an AI-extracted KPI, we should record the correction so future similar extractions are nudged toward the same pattern. Same posture as the manual-override v0.2 proposal in `docs/brand_enrichment_workflow.md`.
8. **Deal-level pitch_history** — if a re-engagement pitch came from our outreach system, `originated_from_pitch_enrollment_id` links the deal to the pitch that won it. v0.2: full enrollment-to-deal conversion analytics in `scripts/analyze_outreach.py`.
