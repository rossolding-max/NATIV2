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

## M6 implementation notes (shipped vs deferred)

M6 ships the REST + service surface for brand-deal capture and the KPI
honesty-floor enforcement. Routes (all under `/api/v1`):

| Endpoint | Action |
|---|---|
| `POST   /talents/{talent_id}/brand-deals` | Create deal + auto-link the matching `talent.data.previous_brands[]` light entry by `deal_id` FK |
| `GET    /talents/{talent_id}/brand-deals?outcome=…` | List per-talent (optional outcome filter — indexed column) |
| `GET    /brand-deals/{deal_id}` | Fetch by id |
| `PATCH  /brand-deals/{deal_id}` | Deep-merge JSONB + re-run honesty-floor validation |
| `POST   /brand-deals/{deal_id}/outcome` | Set the indexed outcome enum (writes the column + JSONB mirror) |
| `DELETE /brand-deals/{deal_id}` | Soft-delete (sets `is_deleted = true`) |

**Honesty floor enforced server-side.** Every populated KPI must carry
`value` + `source` (from the shared `kpiMetric` schema) + `as_of` (M6
extension). The validator returns 422 with a structured `field` path
so the UI can surface inline errors. Suspicious-but-allowed values
(engagement_rate_pct > 100, > 30% unusually high, future as_of) are
logged as `brand_deal_suspicious_value` events for the agent to review.

**Industry inference reuses M5.** When the caller omits `industry_id`,
`brand_history_enrichment.resolve_industry(brand_name)` fires — exact
match in `data/brand_industry_map.json`, then Exa+LLM fallback. M6
fails the create with 422 if no industry can be resolved (since
downstream phases need it for filtering).

**Memo skeleton wired.** Each create emits an idempotent
`memo_type="brand_deal_kpi_pattern"` memo with
`scope="industry_pattern"` and tags `{talent_ids, brand_ids,
industry_ids, deal_ids, topics: ["kpi_insight"]}` so M7 brand-discovery
retrieval has data to read against. Real LLM-driven pattern
classification lands with M7.

**Out of scope for M6:**
- **Media-pack extraction → brand_deal** (Path 1 in this doc) — deferred
  to V2; the agent is the source of truth, not a drifting PDF.
- **Platform-API nightly auto-pull** (Path 3) — deferred to M7/M9 when
  the deal pipeline + post-detection cron land.
- **`archived_from_deal_id` bidirectional FK** — M6 ships the column;
  M9's deal-close handler writes it.
- **Cool-down + renewal-eligibility computation** — fields persist; M7
  Search 1 reads them.
- **`vs_industry_benchmark`** — field persists; M11/M15 packs derive
  it.

## Open questions for v0.2

1. **Industry benchmarks file** — the big v2 deliverable that unlocks `past_campaign_beat_benchmark` (currently dormant). Source: a curated `data/industry_kpi_benchmarks.json` from Influencer Marketing Hub / HypeAuditor / Tribe Dynamics public reports. ~20 industries × 5 platforms × ~6 metrics = ~600 benchmark values to author.
2. **Brand-side reporting integration** — some brands provide formal post-campaign reports (Looker dashboards, custom PDFs). Worth a parser path that extracts conversions / sales_attributed directly from those.
3. **Multi-creator campaigns** — when 3 creators run the same campaign for a brand, today each creator has their own deal record. Worth modelling the campaign-level aggregate so the user can see "this brand spent $X total across N creators".
4. **EMV integration** — `kpis.emv_usd` is in the schema. Sourcing requires Tribe Dynamics / HypeAuditor (paid). v2 vendor decision.
5. **Audience-overlap measurement** — `audience_overlap_with_brand_target_pct` is currently a free input. Could be computed from IAB segment overlap if the brand publishes their target demographics. Worth a structured "brand target audience profile" addition to `brand_industry_map.json`.
6. **Renewal pipeline view** — UI surface that shows all deals approaching `renewal_eligibility_date` in the next 30 days, sorted by past-campaign success. Phase 3a/3b can pre-stage outreach for these.
7. **Manual override layer for AI extraction** — when the talent corrects an AI-extracted KPI, we should record the correction so future similar extractions are nudged toward the same pattern. Same posture as the manual-override v0.2 proposal in `docs/brand_enrichment_workflow.md`.
8. **Deal-level pitch_history** — if a re-engagement pitch came from our outreach system, `originated_from_pitch_enrollment_id` links the deal to the pitch that won it. v0.2: full enrollment-to-deal conversion analytics in `scripts/analyze_outreach.py`.

## v2 spec — onboarding-stage contact capture + cross-deal personal profile + call transcripts

**Status:** spec'd, not yet built. Lands as a discrete v2 milestone — see `docs/project_plan.md` v2-CRM-01.

**The gap in v0.1:**
v0.1 already supports rich `brand_deal` records linked to `brand_contact` via `main_brand_contact_id`, but two things are missing operationally:
1. The M6 backfill wizard (this doc, sources A + B) doesn't prompt for the contact at the brand — agents skip it because there's no field-collection UI.
2. The M16 archive flow doesn't actively maintain a back-reference from the contact to all their deals.

v2 closes both gaps without breaking any existing schema.

### The v2 flow at M6 backfill (extends source B — manual entry)

After the agent enters the deal scalars (brand, dates, fee, KPIs, outcome), an additional "Who did you work with at the brand?" sub-form appears:
- Name (required if the sub-form is filled in) — first + last.
- Title / role at the brand.
- LinkedIn URL.
- Email (encrypted at rest via the existing pgcrypto column).
- Phone (encrypted; same treatment).
- Instagram handle + TikTok handle (public identifiers, stored unencrypted; M9 schema already supports these via `social_handles`).
- "Other channels" expander — WhatsApp / Telegram / personal email via `social_handles`.
- Relationship notes (free text → `brand_contact.notes`).

### Resolve-or-create logic

New service `app/services/contact_match_or_create.py`:

```
1. Match cascade:
   a. (brand_id, linkedin.url)  exact match wins
   b. (brand_id, email.address) secondary
   c. (brand_id, normalized_name) fuzzy fallback — agent confirms when ambiguous
2. On match  → reuse existing contact_id; UI shows "we already have a record for this person"
3. On no-match → INSERT new brand_contact with:
   - is_placeholder = true
   - verification_sources = [{source: "manual_backfill_m6", fetched_at: now}]
   - confidence = 0.7 (agent-entered baseline; M8 enrichment recalibrates)
4. Single transaction:
   - INSERT brand_deal row with main_brand_contact_id = resolved_or_new
   - APPEND brand_deal_id to brand_contact.historical_deal_ids[]
```

### New schema fields (see `schemas/brand_contact.schema.json` + `schemas/brand_deal.schema.json`)

- `brand_contact.historical_deal_ids[]` — back-references to every brand_deal.deal_id where this contact was main OR additional. Populated by (a) M6 backfill, (b) M16 archive (closed_from_pipeline source).
- `brand_contact.call_transcript_ids[]` — back-references to every call_transcript.transcript_id linking this contact (see Call transcripts section below).
- `brand_deal.additional_brand_contact_ids[]` — secondary contacts on the deal (e.g. legal + procurement + champion who made the intro). Each contact's `historical_deal_ids[]` gets back-referenced.
- `brand_deal.source` — discriminator: `backfilled_at_onboarding` / `closed_from_pipeline` / `manual_import` / `data_migration`. Drives CRM person-profile grouping ("historical deals" vs "deals you closed via this system") and analytics (close-rate by source).
- `brand_deal.call_transcript_ids[]` — call transcripts linked to a specific historical deal (e.g. the discovery call that opened the conversation, the post-mortem 6 months later).

### Cross-phase data lineage (post-v2)

| Event | brand_deal change | brand_contact change |
|---|---|---|
| M6 backfill — agent enters historical deal + contact | INSERT with source="backfilled_at_onboarding", main_brand_contact_id=X | Resolve-or-create. If new: INSERT placeholder. APPEND deal_id to historical_deal_ids[]. |
| M8 enrichment runs on a placeholder | unchanged | UPDATE: is_placeholder=false, Apollo + LinkedIn fields merged. historical_deal_ids[] preserved. |
| M9 outreach — interested reply creates pipeline deal | no brand_deal write yet | APPEND pitch_history entry; deal.deal_id surfaces in CRM via live join (not in historical_deal_ids[] until archive). |
| M16 archive — pipeline deal hits archived | INSERT new brand_deal row with source="closed_from_pipeline", archived_from_deal_id=<pipeline_id>, main_brand_contact_id=<deal.primary_contact_id>, KPIs copied from deal.data.close.final_kpis | APPEND new bd_xxx to primary contact's historical_deal_ids[] AND each additional contact. |
| Agent edits contact title | unchanged | UPDATE; if title's brand_id changes, append to tenure.previous_employers[] (the job-move case — same person, new employer). |

### The CRM person-profile view (new REST endpoint)

`GET /api/v1/brand-contacts/{contact_id}/full-profile` returns a one-round-trip composite:
- The contact row (identity + channels + tenure + decision-role).
- `historical_deal_ids[]` expanded inline to full brand_deal rows (newest first).
- Live join `SELECT * FROM deal WHERE primary_contact_id = contact_id` for ACTIVE pipeline deals (these aren't in historical_deal_ids[] yet).
- Pitch history (already in the contact schema's `pitch_history[]`).
- Call transcripts (newest first).

### Call transcripts in the CRM (NEW in v2 — see `schemas/call_transcript.schema.json`)

The CRM can store recorded call transcripts attached to one or more contacts. Use cases: discovery call notes, pitch call transcripts, general catch-ups, negotiation calls, renewal check-ins, post-campaign performance reviews. Each transcript carries:
- The raw file in S3/MinIO (text / markdown / VTT / PDF / docx; up to 50MB).
- LLM-generated structured summary (tl;dr, key takeaways, objections raised, next steps), key quotes, action items, overall sentiment, topic tags — all Haiku-produced on upload.
- Optional links to: pipeline deal (`linked_deal_id`), historical brand_deal (`linked_brand_deal_id`), originating outreach enrollment (`linked_enrollment_id`), the talent(s) the agency was representing.
- Compliance metadata: recording consent flag, consent basis, sensitivity flag, retention policy (default 7y, legal-hold opt-in).
- Audit fields: uploaded_by_agent_id, source (manual_upload / Otter / Fireflies / Grain / etc).

Once uploaded, transcripts feed three downstream consumers:
1. **CRM person-profile view** — agent sees every call this person has been on, sorted by date, with quick-skim summaries.
2. **M11 Discovery Prep Pack** — when prepping a follow-up call on a repeat brand, the researcher subagent pulls the most recent transcripts for the brand_contact + brand_deal + linked talent into the bundle. ("Last call with Sarah ended with her saying she'd come back in Q3 with a budget number — that was 4 weeks ago.")
3. **Memo writes** — action items deemed strategically important auto-write into the memo store (M2) tagged with brand_ids + talent_ids + topics, so future packs see them as a learning even when the transcript itself isn't pulled into context.

### REST surface (v2)

- `POST /api/v1/call-transcripts` — multipart upload. Body: file + JSON metadata (`{kind, occurred_at, attendees, linked_contact_ids, linked_deal_id?, linked_enrollment_id?, linked_talent_ids?, source, recording_consent_obtained, consent_basis}`).
- `POST /api/v1/brand-contacts/{contact_id}/call-transcripts` — shortcut, pre-fills `linked_contact_ids=[contact_id]`.
- `POST /api/v1/deals/{deal_id}/call-transcripts` — shortcut, pre-fills `linked_deal_id` + auto-resolves `linked_contact_ids` from `deal.primary_contact_id` + `additional_contact_ids`.
- `GET /api/v1/brand-contacts/{contact_id}/full-profile` — the composite person profile above.
- `GET /api/v1/call-transcripts/{tx_id}` — full record (signed S3 URL for raw file, 15-min TTL).
- `POST /api/v1/call-transcripts/{tx_id}/resummarize` — re-run Haiku over the raw file (e.g. after the schema's summary template evolves).
- `PATCH /api/v1/call-transcripts/{tx_id}` — agent edits summary / action_items / agent_notes (edits preserved across resummarize).
- `DELETE /api/v1/call-transcripts/{tx_id}` — refuses if `retention_policy.legal_hold=true`; soft-delete otherwise.

### v2 migrations

- Alembic migration adds the new fields to brand_contact / brand_deal (JSONB-stored, so the migration is index changes only — no column adds for the array fields themselves).
- New `call_transcript` SQLA table with FK to brand_contact + brand_deal + deal + pitch_enrollment.
- Backfill script: for every existing brand_deal with `main_brand_contact_id` set, append the deal_id to that contact's `historical_deal_ids[]`. Idempotent — re-runnable.
