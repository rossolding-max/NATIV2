# Performance Report Workflow (Phase 4.9)

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the post-campaign performance report — the artefact that closes Phase 4 DELIVERY into CLOSE and unblocks the auto-archive into Phase 1.5 brand_deals. Aggregates KPIs captured during the `performance_window` into a final snapshot + benchmark comparisons + LLM-drafted narrative. Soft agent gate; sending IS approval.

**Pairs with:**
- `schemas/performance_report_pack.schema.json` — the data contract.
- `schemas/deal.schema.json` — `delivery.interim_kpi_snapshots[]` (per-post in-flight KPI captures); `close.performance_report_pack_ids[]` + `latest_performance_report_pack_id` (FK list); `close.final_performance_report_attachment_id` + `close.final_kpis` (auto-populated on report send; gate auto-archive).
- `docs/invoice_workflow.md` (Phase 4.8) — sibling DELIVERY → CLOSE flow. Detection cron + KPI capture cron are coordinated (both poll the same platform APIs during overlapping windows).
- `docs/deal_lifecycle_workflow.md` (Phase 4) — DELIVERY substage `performance_window` is where KPI capture runs; CLOSE substage `post_campaign_reporting` is where this artefact lives.
- `docs/brand_deals_workflow.md` (Phase 1.5) — on auto-archive, this pack's `kpis` write into `brand_deal.kpis` (verbatim — same kpiMetric shape).

## Goal

Generate the post-campaign report the brand was promised — what got reached, what worked, what to do next time. Required to (a) deliver on the campaign deliverable (most contracts oblige a report), (b) populate `deal.close.final_kpis` so auto-archive can fire, (c) feed the talent's historical brand_deal record with quality KPI data.

Locked-in design decisions:
1. **Auto-fire on `performance_capture_window_ends_at`** — cron generates draft when the window closes (typically 30 days after last post). Agent reviews + sends.
2. **Soft gate** — agent reviews + edits before send; sending IS approval. Parallel to invoice pattern; lighter than contract.
3. **KPI capture is continuous during the window** — separate cron polls platform Insights APIs daily, writes to `deal.delivery.interim_kpi_snapshots[]`. Performance report aggregates these into the final snapshot.
4. **Three benchmark sets** — vs_industry (from `data/industry_kpi_benchmarks.json`, v2), vs_talent_historical (averaged across comparable past `brand_deals`), vs_brand_stated_targets (extracted from `discovery_debrief.objectives_heard[]`).
5. **No e-sign / no legal gate** — performance reports don't carry legal weight; agent's review is sufficient.

## When it fires

| Trigger | Behaviour |
|---|---|
| `performance_capture_window_ends_at < now` reached | Auto-fire — cron generates v1; agent notified in morning summary. |
| Agent clicks "Draft report" before window end | Generates with whatever KPI data is captured so far. Useful for early delivery to eager brands; agent typically waits for window. |
| Agent requests full regenerate | NL feedback; new v(N+1); parent retained. |
| Agent requests section regenerate | `target_sections`; untargeted carry from parent. |
| `kpi_refresh` trigger | Cron re-fires when new KPI data arrives after initial generation (e.g. platform API late-reporting; viral pickup pushing reach numbers up). Agent sees "updated KPIs available — regenerate report?" |

## KPI capture (the upstream layer)

Runs throughout the `performance_window` (typically 30 days after last post). Stores per-post + per-capture-timestamp snapshots on `deal.delivery.interim_kpi_snapshots[]`.

```
Window opens: deal.delivery.performance_capture_window_starts_at
  (set to first deliverable's posted_at when first posting_schedule entry confirms)

Daily KPI cron during window:
  For each deal in performance_window substage:
    For each post in posting_schedule[] with posted_at set:
      Query platform Insights API for current KPIs
       · Instagram → Meta Graph /{ig-media-id}/insights
       · TikTok → TikTok Display API metrics
       · YouTube → YouTube Analytics API
       · Other (manual entry / brand reported in v0.1)
      Write snapshot to deal.delivery.interim_kpi_snapshots[]:
        {
          captured_at: now,
          post_url, deliverable_ref, platform,
          kpis: { reach: {value, source, as_of}, engagement_rate_pct: ..., ... }
        }

Window closes: deal.delivery.performance_capture_window_ends_at
  (typically posted_at_of_last_post + 30d)

  → Triggers performance_report_pack generation
```

The KPI cron schema lives on the deal (`delivery.interim_kpi_snapshots[]`); the report pack reads from there + aggregates.

## Generation pipeline

```
Trigger fires (cron or agent)
  │
  ▼ STAGE A — Aggregate KPIs from interim snapshots
  │  For each post in deal.delivery.interim_kpi_snapshots[]:
  │   Take the most recent snapshot per post (KPIs grow over time;
  │   last snapshot has the highest values).
  │  Per-post KPIs → per_post_kpis[]
  │  Sum/average → aggregate kpis{} (e.g. total reach = sum of per-post reach;
  │   engagement_rate_pct = engagement_total / impressions weighted average)
  │  Each metric carries source provenance (mostly platform_verified).
  │
  ▼ STAGE B — Benchmark comparisons (3 sets)
  │  vs_industry: lookup `data/industry_kpi_benchmarks.json` by industry_id
  │   (v2 — empty in v0.1 until benchmark file ships)
  │  vs_talent_historical: load talent's past `brand_deals` filtered to similar
  │   industry + campaign_type; average their kpis; compute delta_pct
  │  vs_brand_stated_targets: if discovery_debrief.objectives_heard[] mentions
  │   numeric targets (e.g. "reach 200k"), extract + compare
  │  Each comparison: { this_campaign_value, benchmark_value, delta_pct,
  │   performance_label, benchmark_source }
  │
  ▼ STAGE C — Narrative drafting (3 LLM passes, prompt-cached)
  │  Pass 1: executive_summary — 3-line top-line ("Reach 2.3x category;
  │   engagement +18% vs talent's last activewear deal; secondary objective
  │   trial-redemption not directly measured")
  │  Pass 2: what_worked — which deliverables outperformed + why
  │   (cite per_post_kpis differences; identify the strongest format/timing)
  │  Pass 3: learnings — recommendations for future campaigns
  │   (tone = forward-looking; cite specific benchmark deltas)
  │  Optional Pass 4: audience_resonance — if comments KPIs are populated,
  │   summarise themes (sentiment, recurring questions, brand affinity signals)
  │
  ▼ STAGE D — Compose
  │  Template (agency-wide default; could be overridable per agency in v0.2):
  │   Executive Summary → KPI Tables (aggregate + per-post) → Benchmark Callouts
  │   → What Worked → Learnings → Audience Resonance (optional) → Appendix
  │  → composed_markdown
  │
  ▼ STAGE E — Render
  │  composed.md → report.pdf (Puppeteer) + report.md (canonical)
  │  Optional report.html for in-browser viewing
  │  Written to data/deals/{deal_id}/performance_report_packs/v{N}_artifacts/
  │
  ▼ STAGE F — Agent review (soft gate)
  │  Agent reviews rendered PDF + KPI values + narrative
  │  Edit any KPI value (with reason — captured in agent_edits[]);
  │   edit narrative; trigger regen
  │  Click Send → agent_review.sent_at set, triggers:
  │   · deal.close.final_performance_report_attachment_id = report.pdf path
  │   · deal.close.final_kpis = this pack's kpis{} (verbatim copy)
  │   · deal.close.performance_report_pack_ids[] appended; latest pointer updated
  │   · If deal.close.all_invoices_paid_at also set → auto-archive fires
```

## Default report structure

| Section | Content | LLM-drafted? |
|---|---|---|
| Title | Brand × Talent campaign name; campaign dates | No |
| Executive summary | 3-line top-line outcome | Yes (Pass 1) |
| Headline KPIs | 4-6 hero metrics with benchmark labels (e.g. "2.3M reach, 2.3x category average") | Computed (kpis + benchmark_comparisons) |
| Per-post breakdown | Table: post URL, platform, posted_at, key KPIs | Computed (per_post_kpis) |
| Benchmark comparisons | 3 sub-sections: vs industry, vs talent historical, vs brand stated targets | Computed (benchmark_comparisons) |
| What worked | Qualitative analysis of strongest deliverables | Yes (Pass 2) |
| Learnings + recommendations | Forward-looking guidance for future campaigns | Yes (Pass 3) |
| Audience resonance (optional) | Sentiment + theme analysis from comments KPIs | Yes (Pass 4, if comments data captured) |
| Appendix | Full KPI table + capture methodology + sources | Computed |

## Auto-archive interaction (closes the loop)

```
Auto-archive conditions (all must be true):
  1. deal.close.all_invoices_paid_at SET (from Phase 4.8 — last invoice paid)
  2. deal.close.final_performance_report_attachment_id SET (from this phase, agent sent report)
  3. deal.close.final_kpis populated (from this phase, copied on send)

When all three true → orchestrator fires:
  · Build Phase 1.5 brand_deal record from deal data
  · brand_deal.kpis = deal.close.final_kpis (verbatim — same kpiMetric shape)
  · brand_deal.originated_from_pitch_enrollment_id = deal.originating_enrollment_id
  · brand_deal.archived_from_deal_id = this deal_id
  · Write data/brand_deals/{talent_id}.json
  · Set deal.close.archived_to_brand_deal_id + archived_at
  · Transition deal.stage = "archived", is_terminal: true, is_won: true
```

The performance report is the last gate before the deal becomes part of the talent's historical record.

## Storage

```
data/deals/{deal_id}/
  performance_report_packs/      # Phase 4.9 (NEW)
    v1.json
    v1_artifacts/{report.md, report.pdf, report.html}
    v2.json
    v2_artifacts/...
```

All gitignored.

## Integration touchpoints

| Existing piece | How Phase 4.9 plugs in |
|---|---|
| **`deal.delivery.interim_kpi_snapshots[]`** | NEW field. Daily KPI cron writes here during performance_window. Report aggregates from here. |
| **`deal.delivery.performance_capture_window_*`** | Existing timestamps. Window-end triggers auto-fire. |
| **`deal.proposal.fee_usd` + `deliverables[]`** | Source for fee-vs-results analysis (CPM, CPE per fee × reach/engagement). |
| **`deal.lead.discovery_debrief.objectives_heard[]`** | Source for `vs_brand_stated_targets` benchmark — what brand said they wanted. |
| **`brand_deals/{talent_id}.json`** | On send, `kpis` flows into `deal.close.final_kpis`; on auto-archive, that flows into the new brand_deal record's `kpis`. Same kpiMetric shape — clean carry. |
| **Phase 4.8 invoice pipeline** | Sibling DELIVERY → CLOSE flow. Both must complete (all invoices paid + report sent) for auto-archive. Independent triggers; combined gate. |
| **`talent.platforms[].api_credentials`** | KPI cron uses same oAuth tokens captured at Phase 1 onboarding for Phase 4.8 detection. |

## Failure handling

| Failure | Behaviour |
|---|---|
| Platform API rate-limited mid-capture | Snapshot for this day fails; KPI cron retries next day; report aggregates over whatever's available |
| Talent disconnects platform account mid-window | Surface to agent: "Reconnect needed — KPIs frozen since {date}". Report generates with what's captured + flags coverage gap in narrative. |
| Post deleted mid-window | Last snapshot before deletion captured; report shows final pre-delete values + flags. |
| Brand-reported KPIs differ from platform-verified | Agent can override via agent_edits[] with reason captured. Both values traceable in audit log. |
| Late-reporting (platform updates KPIs days after capture) | `kpi_refresh` regen trigger fires; agent decides whether to send updated v(N+1) to brand. |
| Comments KPIs empty (no engagement data captured) | Audience resonance section omitted; LLM doesn't fabricate themes. |
| No comparable past brand_deals for vs_talent_historical | Benchmark omitted with note "First {industry} campaign for this talent — no historical comparison available." |
| `industry_kpi_benchmarks.json` missing (v0.1) | vs_industry benchmarks section omitted with note "Industry benchmarks ship in v2." |
| Agent waits too long to send (e.g. 60d) | No timeout; report stays in draft. UI surfaces "Report drafted {N} days ago — send to brand?" reminder. |
| Auto-archive fires before report sent | Cannot happen — auto-archive requires final_performance_report_attachment_id which only sets on agent_review.sent_at. Guard. |

## Cost profile

Per-pack: 3-4 Sonnet passes (narrative drafting). ~15-25k input tokens (KPI tables + comparables + objectives) + ~6-10k output tokens. Estimated **$0.10-0.25 per generation**. Cheaper than proposal/contract packs (less context; bounded narratives).

Platform API costs: same APIs as Phase 4.8 detection; marginal additional cost (KPI endpoints alongside post-listing endpoints).

## v0.1 explicit non-goals

- **`industry_kpi_benchmarks.json`** — schema-ready (`vs_industry` block exists) but the actual benchmark data file is v2. v0.1 sections omit vs_industry with a note.
- **Interactive dashboards** — report is PDF-only in v0.1. v0.2 could add an HTML dashboard view with filterable per-post breakdowns.
- **Sentiment analysis on comments** — `audience_resonance` narrative section attempts pattern extraction but doesn't run sentiment ML in v0.1. v2 with proper sentiment classifier.
- **Brand-side annotation portal** — brand cannot annotate the report directly. v0.2.
- **Multi-language reports** — English-only in v0.1.
- **Real-time KPI ticker during window** — agent sees daily snapshots; no live updates. v0.2.

## v0.2 open questions

1. **Per-platform attribution model** — when a post drives a click that converts 3 days later, which post gets credit? UTM-driven attribution. v0.2.
2. **Sales attribution integration** — `sales_attributed_usd` KPI exists but currently only populated if brand reports it. v0.2 could integrate with brand's analytics (Shopify, GA4) via Phyllo or direct.
3. **Sentiment ML** — Hugging Face / Anthropic-built classifier for comments themes.
4. **Auto-generate next-deal pitch from report** — strong learnings could seed a follow-on pitch ("Based on this campaign's performance, here's what we'd do next"). Cross-pollinates Phase 3b.
5. **A/B post performance** — when multiple deliverables of same format, statistical significance of per-post deltas (e.g. "Reel 1 outperformed Reel 2 by 23% — caption length / time of day differences").
6. **Brand-customisable report template** — some brands want their own report format. v0.2 = per-brand template override.
7. **Performance report → case study generation** — if deal outcome is `successful` or `successful_renewed`, auto-draft a case study from this report for talent's media kit + agency's marketing.
