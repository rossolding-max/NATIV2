# Deal Lifecycle Workflow (Phase 4)

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the deal pipeline — how an `interested` reply from Phase 3b outreach becomes a tracked deal that moves through 5 stages until it's either won (paid + archived) or lost (with a structured loss reason).

**Pairs with:**
- `schemas/deal.schema.json` — the data contract.
- `docs/outreach_workflow.md` (Phase 3b) — reply classification = `interested` triggers Phase 4 deal creation.
- `docs/brand_deals_workflow.md` (Phase 1.5) — won deals auto-archive here as historical brand-deal records.
- `docs/contact_enrichment_workflow.md` (Phase 3a) — deals reference the buyer + additional contacts at the brand.
- `docs/agency_setup_workflow.md` (Phase 0) — `assigned_agent_id` ties each deal to the agency's agent.

## Goal

Turn the pipeline from "we sent a pitch" into "we got paid" with a clear, auditable trail. Every deal has:
- A current `stage` + granular `substage`
- An audit log of every state transition (`stage_history[]`)
- A `next_action` + `next_action_due_at` driving the agent's daily task list
- Per-stage data blocks that get populated as the deal progresses (lead → proposal → contract → delivery → close)
- Attachments (briefs, contracts, content drafts, invoices) referenced from a flat `attachments[]` array
- Append-only notes for any agent context that doesn't fit elsewhere
- Auto-archive into Phase 1.5 brand_deals on successful close (closes the loop)
- Structured loss reasons on failure (enables funnel analytics)

**Ultimate objective:** signed + delivered + paid brand deals, with full traceability from the originating pitch through to the final payment + performance report.

## The 5-stage lifecycle

```
   PHASE 3b reply: outcome=interested
              │
              ▼
   ┌───────────────────────────────────────────────────────────┐
   │ STAGE 1: LEAD                                              │
   │   new_lead → initial_call_scheduled → initial_call_done   │
   │   → brief_received → qualified                             │
   │                                                             │
   │   Exit: qualified ▶ PROPOSAL                               │
   │         disqualified ▶ LOST                                │
   └────────────────┬──────────────────────────────────────────┘
                    │
                    ▼
   ┌───────────────────────────────────────────────────────────┐
   │ STAGE 2: PROPOSAL                                          │
   │   proposal_drafting → proposal_sent → under_review        │
   │   → negotiation → terms_agreed                             │
   │                                                             │
   │   Exit: terms_agreed ▶ CONTRACT                            │
   │         lost ▶ LOST                                        │
   └────────────────┬──────────────────────────────────────────┘
                    │
                    ▼
   ┌───────────────────────────────────────────────────────────┐
   │ STAGE 3: CONTRACT                                          │
   │   contract_drafting → in_review_brand / in_review_talent  │
   │   → contract_revisions → contract_executed                 │
   │                                                             │
   │   Exit: contract_executed ▶ DELIVERY                       │
   │         contract_failed ▶ LOST                             │
   └────────────────┬──────────────────────────────────────────┘
                    │
                    ▼
   ┌───────────────────────────────────────────────────────────┐
   │ STAGE 4: DELIVERY                                          │
   │   pre_production → content_in_production →                │
   │   pending_brand_approval → revisions_requested →          │
   │   approved_for_posting → live → performance_window         │
   │                                                             │
   │   Exit: performance_window complete ▶ CLOSE                │
   │         killed ▶ LOST (rare; usually after major dispute)  │
   └────────────────┬──────────────────────────────────────────┘
                    │
                    ▼
   ┌───────────────────────────────────────────────────────────┐
   │ STAGE 5: CLOSE                                             │
   │   invoice_sent → invoice_paid →                            │
   │   post_campaign_reporting → archived                       │
   │                                                             │
   │   Exit: archived ▶ Phase 1.5 brand_deals entry created     │
   └───────────────────────────────────────────────────────────┘
```

## Stage-by-stage

### Stage 1 — LEAD

**Entry:** Phase 3b outreach classifies a reply as `interested`. The orchestrator creates a deal record with:
- `originating_enrollment_id` = the pitch enrollment
- `primary_contact_id` = the contact who replied
- `stage: "lead"`, `substage: "new_lead"`
- `assigned_agent_id` = the agent who owned the outreach
- `next_action: "Schedule discovery call"` + `next_action_due_at: +3 days`

**Substages:**
- `new_lead` — just created
- `initial_call_scheduled` — call booked
- `initial_call_completed` — call happened; agent has scoped what brand wants
- `brief_received` — brand has sent a formal brief (text or attachment)
- `qualified` — agent decides this is worth a proposal → transitions to `proposal_drafting`
- `disqualified` — terminal; populates `loss` block

**Data captured (`deal.lead`):**
- `discovery_call_*` timestamps + free-text notes
- `brief_text` / `brief_attachment_id` + `brief_received_at`
- `qualification_decision` + `qualification_rationale` (the WHY — used by analytics to understand what we accept/reject)
- `discovery_prep_pack_ids[]` + `latest_prep_pack_id` — FK references to the Phase 4.5 prep packs generated for this deal's discovery call (see below)

**Discovery call prep (Phase 4.5):**

On transition to `initial_call_scheduled`, the orchestrator auto-fires the Phase 4.5 prep generation pipeline (`docs/discovery_prep_workflow.md`):
1. Gather context from the deal + talent profile + brand_candidate + brand_contact + originating enrollment + comparable brand_deals + top-scoring pitch_angles
2. Run Exa external research on the brand (recent campaigns, news, contact background, competitor landscape)
3. Three Claude Sonnet passes (prompt-cached): briefing notes → agenda → slides[]
4. Render artefacts: live HTML deck, leave-behind HTML deck, PDF variants, speaker notes md, briefing notes md, agenda md, editable PPT (via slide skill)
5. Write to `data/deals/{deal_id}/prep_packs/v{N}.json` + artefact files
6. Append to `deal.lead.discovery_prep_pack_ids[]`, set `deal.lead.latest_prep_pack_id`
7. Surface in agent's morning summary 24h before the call

Agent can iterate before the call via natural-language feedback ("tone down slide 4, drop sustainability angle, beef up commercial range") → produces v(N+1). Old versions retained. **V1 stays locked unless agent asks** — upstream data refresh does NOT auto-regen.

**Exits:**
- Transition to PROPOSAL on `qualified`
- Mark terminal + `loss` on `disqualified` (with reason from the enum)
- LLM can suggest `next_action` updates throughout (e.g. "Brief mentions launch date — suggest proposing sponsored series rather than single post")

### Stage 2 — PROPOSAL

**Entry:** `qualified` from LEAD or manual creation in PROPOSAL.
**Exit:** Verbal/written agreement on terms → CONTRACT.

**Substages:**
- `proposal_drafting` — agent building the proposal
- `proposal_sent` — sent to brand
- `under_review` — brand internally reviewing
- `negotiation` — back-and-forth on specific terms
- `terms_agreed` — verbal yes; pending formal contract
- `lost` — terminal

**Data captured (`deal.proposal`):**
- `proposal_attachment_id` (the PDF)
- `proposal_sent_at`
- Deliverables (same shape as brand_deal.deliverables — carries cleanly to Phase 1.5 on archive)
- `fee_usd` + currency + original amount
- `usage_rights_granted[]` + `exclusivity{}` + `additional_compensation[]`
- `negotiation_log[]` — chronological back-and-forth with what changed at each round
- `terms_agreed_at` + `agreed_final_terms_summary` — the verbal/written agreement that the contract will codify

**Exits:**
- Transition to CONTRACT on `terms_agreed`
- Mark terminal + `loss` on `lost` (most common loss point — `budget`, `terms_disagreed`, `competitor_won`)

### Stage 3 — CONTRACT

**Entry:** `terms_agreed` from PROPOSAL.
**Exit:** Both parties signed → DELIVERY.

**Substages:**
- `contract_drafting` — legal language being written
- `contract_in_review_brand` — brand legal/exec reviewing
- `contract_in_review_talent` — talent reviewing
- `contract_revisions` — changes requested
- `contract_executed` — both signed → transitions to `pre_production`
- `contract_failed` — couldn't agree on terms (terminal)

**Data captured (`deal.contract`):**
- `draft_contract_attachment_id` + `contract_attachment_id` (final signed)
- `e_sign_provider` (v0.1: always `manual`; v2: `docusign` / `pandadoc` / `hellosign`)
- Timestamps for: drafting started, sent to brand, sent to talent, signed by talent, signed by brand, executed
- `amendment_log[]` — post-execution scope changes / extensions

**v0.1 manual approach:** agent uploads PDF, manually sets `*_signed_at` timestamps. Attachment lives in `attachments[]` with `type: "contract"`.

**v2 API integration:** DocuSign/PandaDoc webhook auto-populates `talent_signed_at` + `brand_signed_at` + `contract_executed_at` and uploads the final PDF.

**Exits:**
- Transition to DELIVERY on `contract_executed`
- Mark terminal + `loss` on `contract_failed` (reason typically `terms_disagreed`)

### Stage 4 — DELIVERY

**Entry:** `contract_executed`.
**Exit:** Performance capture window closed → CLOSE.

**Substages (per deliverable; deal-level substage = most-active state):**
- `pre_production` — products shipped, concepts being developed
- `content_in_production` — talent shooting / writing
- `pending_brand_approval` — drafts submitted for brand sign-off
- `revisions_requested` — brand sent notes back
- `approved_for_posting` — content cleared
- `live` — content posted to platform
- `performance_window` — 30-day post-launch KPI capture window

**Data captured (`deal.delivery`):**
- `production_kickoff_at`, `products_shipped_*_at`
- `content_drafts[]` — per-deliverable versioned drafts with brand review status
- `posting_schedule[]` — scheduled + actual post URLs
- `performance_capture_window_*` timestamps — drive when the platform-API auto-pull cron starts/stops refreshing KPIs

**Cross-system integration:**
- `content_drafts[].draft_url` + `posting_schedule[].post_url` — the actual content references
- Performance capture window aligns with Phase 1.5 brand_deals KPI auto-refresh: when the window opens, the cron starts pulling `kpis.*` from IG/TikTok/YouTube Insights APIs for the `post_url` URLs

**Exits:**
- Transition to CLOSE when `performance_window` ends (typically 30 days after last post). At this point, final KPI snapshot is taken.
- Mark terminal + `loss` on `killed` (rare — usually means a major dispute mid-delivery)

### Stage 5 — CLOSE

**Entry:** Performance window closed; final KPIs captured.
**Exit:** Payment received + archive → moves to Phase 1.5.

**Substages:**
- `invoice_sent` — invoice issued to brand
- `invoice_paid` — payment landed
- `post_campaign_reporting` — final performance report delivered to brand (gives them what they paid for AND the case study they can show internally)
- `archived` — auto-archive fires → Phase 1.5 brand_deals entry created

**Data captured (`deal.close`):**
- `invoice_id` (external), `invoice_attachment_id`, `invoice_provider` (v0.1: `manual`; v2: `stripe_invoices` / `xero` / `quickbooks`)
- `invoice_amount_usd`, `invoice_currency`, `invoice_sent_at`, `payment_due_at`
- `payment_received_at`, `payment_method`
- `final_performance_report_attachment_id`
- `final_kpis` — snapshot in brand_deal.kpis shape (carries directly to Phase 1.5 on archive)
- `archived_to_brand_deal_id` — FK to the auto-created entry in `data/brand_deals/{talent_id}.json`
- `archived_at`

**Auto-archive trigger:** when `payment_received_at` is set AND `final_kpis` is populated AND `final_performance_report_attachment_id` is set, the orchestrator fires the archive:
1. Build a Phase 1.5 brand_deal record from this deal's data (deliverables, fee, usage_rights, KPIs, etc.)
2. Set `originated_from_pitch_enrollment_id` on the new brand_deal to this deal's `originating_enrollment_id` (closes the outreach → deal loop)
3. Write to `data/brand_deals/{talent_id}.json`
4. Set this deal's `archived_to_brand_deal_id` + `archived_at`
5. Transition `stage: "archived"`, `substage: "archived"`, `is_terminal: true`, `is_won: true`

## Loss handling

Any non-archived terminal state populates the `loss` block:

```jsonc
"loss": {
  "reason": "budget",         // enum
  "at": "2026-04-30T14:00:00Z",
  "by_agent_id": "sarah-smith",
  "lost_at_stage": "proposal",
  "notes": "Brand had a $5k cap; we couldn't go below $12k.",
  "competitor_brand": null    // populated if reason=competitor_won
}
```

**Loss reasons enum:**
- `budget` — brand budget insufficient
- `timing` — schedules didn't align
- `competitor_won` — brand picked a different creator (captures who in `competitor_brand`)
- `internal_pivot` — brand changed direction internally
- `talent_no_fit` — talent declined (e.g. red-line breach surfaced late)
- `terms_disagreed` — couldn't agree on usage rights / exclusivity / etc.
- `unresponsive` — went dark; assumed lost after N days of no reply
- `compliance_block` — values_red_line conflict surfaced after deal started
- `other` — free-text in `notes`

Analytics consume the loss reason × `lost_at_stage` cross-tab to surface funnel diagnostics: e.g. "30% of LEAD-stage losses are `unresponsive` — maybe our discovery-call cadence is too slow."

## Integration touchpoints

| Existing piece | How Phase 4 plugs in |
|---|---|
| **Phase 3b outreach (`outreach_workflow.md`)** | Reply classification `outcome="interested"` triggers `POST /deals/create` with `originating_enrollment_id` set. The Phase 3b enrollment's `outcome_classification.extracted_signals.asked_for_meeting / asked_for_pricing` flags pre-seed the LEAD substage (e.g. if they asked for a meeting in the reply, jump straight to `initial_call_scheduled`). |
| **Phase 3a contacts (`contact_enrichment_workflow.md`)** | `primary_contact_id` + `additional_contact_ids[]` reference contacts. As the deal progresses, the agent can loop in additional contacts (legal at contract stage, finance at close stage). Each contact's `pitch_history[]` continues to record outcomes throughout. |
| **Phase 1.5 brand_deals (`brand_deals_workflow.md`)** | Auto-archive on close. The deal's `proposal.*`, `delivery.captured_kpis`, `close.final_kpis`, and metadata are mapped into a new `brand_deals[]` entry. `archived_to_brand_deal_id` / `originated_from_pitch_enrollment_id` form the bidirectional link. |
| **Phase 0 agency_profile** | `assigned_agent_id` ties each deal to an agent (v0.1: always the single primary agent; v2: per-deal assignment for multi-agent rosters). Notes + stage_history record `by_agent_id` for audit. |
| **Outreach analytics (`scripts/analyze_outreach.py`)** | Now computes the **full funnel**: `emails sent → delivered → replied → interested → deal created → won`. Per-angle / per-template / per-decision-role conversion-to-won-deal rates are now real metrics, not just reply rates. Deal-stage durations (median days in LEAD, PROPOSAL, etc.) feed pipeline health views. |

## Notifications + reminders

Each deal has a `next_action` + `next_action_due_at`. A daily cron:
1. Loads every non-terminal deal
2. Finds deals where `next_action_due_at < now` → overdue
3. Surfaces in the agent's morning summary
4. Optionally emails the agent if no action taken in N days

The orchestrator updates `next_action` on stage transitions automatically (e.g. on `proposal_sent`, `next_action` becomes "Follow up in 3 days if no reply"; `next_action_due_at` = `proposal_sent_at + 3d`).

LLM may also suggest `next_action` updates based on context (e.g. negotiation_log shows brand last raised exclusivity concern → next_action becomes "Address exclusivity concern in next response").

## Storage

`data/deals/{deal_id}.json` per deal — gitignored (commercial data, signed contracts, invoice amounts, payment records).

Same pattern as other gitignored output: schema lives in repo, data does not. Pipeline view loads all files in the folder; individual deal view loads one.

**v0.1 implementation note:** filesystem JSON works for single-agency, single-machine. Production multi-tenant should move to Postgres + S3 (Postgres for indexed records + workflow state; S3 for `attachments[].url` PDFs/files). Decision deferred per `data/agency_profile.json` pattern.

## State machine — valid transitions

| From substage | Can transition to |
|---|---|
| `new_lead` | `initial_call_scheduled`, `disqualified`, `lost`, `paused` |
| `initial_call_scheduled` | `initial_call_completed`, `disqualified`, `lost`, `paused` |
| `initial_call_completed` | `brief_received`, `qualified`, `disqualified`, `paused` |
| `brief_received` | `qualified`, `disqualified`, `paused` |
| `qualified` | `proposal_drafting` (auto-transition to PROPOSAL stage) |
| `proposal_drafting` | `proposal_sent`, `lost`, `paused` |
| `proposal_sent` | `under_review`, `negotiation`, `terms_agreed`, `lost`, `paused` |
| `under_review` | `negotiation`, `terms_agreed`, `lost`, `paused` |
| `negotiation` | `terms_agreed`, `proposal_sent` (revision), `lost`, `paused` |
| `terms_agreed` | `contract_drafting` (auto-transition to CONTRACT) |
| `contract_drafting` | `contract_in_review_brand`, `contract_in_review_talent`, `contract_failed`, `lost` |
| `contract_in_review_brand` | `contract_in_review_talent`, `contract_revisions`, `contract_executed`, `contract_failed` |
| `contract_in_review_talent` | `contract_in_review_brand`, `contract_revisions`, `contract_executed`, `contract_failed` |
| `contract_revisions` | `contract_in_review_brand`, `contract_in_review_talent`, `contract_failed` |
| `contract_executed` | `pre_production` (auto-transition to DELIVERY) |
| `pre_production` | `content_in_production`, `killed`, `paused` |
| `content_in_production` | `pending_brand_approval`, `killed`, `paused` |
| `pending_brand_approval` | `revisions_requested`, `approved_for_posting`, `killed` |
| `revisions_requested` | `content_in_production`, `pending_brand_approval`, `killed` |
| `approved_for_posting` | `live` |
| `live` | `performance_window` |
| `performance_window` | `invoice_sent` (auto-transition to CLOSE when window ends) |
| `invoice_sent` | `invoice_paid`, `paused` (if dispute) |
| `invoice_paid` | `post_campaign_reporting` |
| `post_campaign_reporting` | `archived` (auto-fires when all archive conditions met) |
| `paused` | any of its origin's onward states (resume) |

Orchestrator rejects any transition not in this table. Manual override flag exists for edge cases but logs a warning.

## Failure handling

| Failure | Behaviour |
|---|---|
| Phase 3b reply classified `interested` but no deal created (orchestrator bug / API failure) | Daily reconciliation cron checks enrollments with `outcome=interested` and no `linked_deal_id`; auto-creates |
| Deal stuck in `proposal_sent` with no reply for 14 days | Auto-suggest transitioning to `unresponsive` → `lost`; agent confirms |
| Auto-archive fails (Phase 1.5 brand_deals write error) | Retry 3x; on failure, leave deal in `post_campaign_reporting` substage, surface to agent; manual archive button available |
| `payment_received_at` set but `final_kpis` empty | Block auto-archive; surface to agent: "Capture final performance KPIs before archiving" |
| Agent manually edits `stage` to an invalid transition | Validation rejects with explicit error; force-override flag available for unusual situations (e.g. resurrecting a `lost` deal) |
| Attachment file size exceeds limit | Limit configured per environment (e.g. 50MB); files larger go to S3 with reference URL only |
| LLM-suggested `next_action` is nonsensical | Agent always has manual override; LLM suggestions are advisory, never auto-applied |

## v2 vendor integrations (deferred)

Per user decision, v0.1 tracks contracts + invoices manually (PDF upload + dates). v2 adds API integrations:

| Concern | v0.1 | v2 vendor options |
|---|---|---|
| E-sign contracts | Manual PDF upload + dates | **DocuSign** (industry standard), **PandaDoc** (better for proposal-to-contract flow), **HelloSign** (Dropbox; cheaper) |
| Invoicing | Manual PDF upload + dates | **Stripe Invoices** (already a payment processor; clean API), **Xero** (UK + global accounting integration), **QuickBooks** (US accounting integration), **Wave** (free for small ops) |
| Payment confirmation | Manual `payment_received_at` | Webhook from Stripe / bank / accounting platform auto-populates |

v2 sub-spec — a proposed new doc `docs/contract_invoicing_integration.md` (not yet written; deliverable for the next phase) will cover the API integration patterns when these vendors are wired up. Schema is already shaped to absorb them: `e_sign_provider` + `e_sign_envelope_id` + `invoice_provider` + `invoice_id` fields exist and accept either manual values or vendor-API populated values.

## Open questions for v0.2

1. **Pipeline forecasting view** — UI rolls up `expected_value_usd` + `expected_close_date` × probability(stage) into a forecasted-revenue chart. Needs per-stage win-probability values (industry standard: lead ~10%, proposal ~25%, contract ~70%, delivery ~95%). Tunable per-agency from observed conversion rates.
2. **Multi-deliverable deals** — large campaigns have 10+ deliverables. The current `delivery.content_drafts[]` + `delivery.posting_schedule[]` arrays handle this but the UI needs a kanban-by-deliverable view for production tracking.
3. **Cross-deal dependencies** — sometimes a brand signs talent for 3 campaigns at once. Currently 3 separate deals; could model as a "deal series" parent record in v0.2.
4. **Auto-suggest next_action from LLM** — currently the orchestrator sets `next_action` on transitions; the LLM could read the full deal context + suggest more sophisticated next actions (e.g. "Negotiation log shows brand prioritises usage rights — propose a 90d whitelisting upgrade in exchange for keeping fee flat").
5. **Stage SLA tracking** — typical lead → close timeline is 30-90 days. If a deal sits in a stage longer than the SLA, flag for review. Per-stage SLA configurable per agency.
6. **Deal-to-deal cloning** — for repeat brands, "duplicate previous deal" speeds up proposal stage massively. v0.2: clone-from-template button that prefills proposal block from the matching brand's most recent successful deal.
7. **Pipeline export** — agencies often need a CSV / PDF export of the pipeline for monthly reports to talents. v0.2 adds export endpoints.
