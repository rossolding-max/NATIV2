# Invoice Workflow (Phase 4.8)

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the invoice pipeline — three layers spanning Phase 4 DELIVERY → CLOSE: (1) deliverable detection via direct platform APIs (Meta Graph + TikTok Display in v0.1; other platforms via Phyllo in v2), (2) invoice generation driven by an LLM-parsed payment schedule from the contract, (3) payment tracking (manual in v0.1; webhook-driven in v2).

**Pairs with:**
- `schemas/invoice_pack.schema.json` — the data contract.
- `schemas/agency_profile.schema.json` — `agency_profile.invoice_template` block is the agency-wide template (captured Phase 0).
- `schemas/deal.schema.json` — `deal.close.invoice_schedule[]` (LLM-parsed from contract.payment_terms; one-time agent gate); `deal.close.invoice_pack_ids[]` (flat FK list of all versions); `deal.close.all_invoices_paid_at` (computed; gates auto-archive). `deal.delivery.posting_schedule[].posted_detection` captures detection provenance.
- `docs/contract_pack_workflow.md` (Phase 4.7) — `commercial_proposal.llm_proposed.payment_terms` is the source string LLM-parses into the invoice schedule on contract execution.
- `docs/deal_lifecycle_workflow.md` (Phase 4) — DELIVERY substage `live` / `performance_window` is where detection runs; CLOSE substages `invoice_sent` / `invoice_paid` are now per-invoice states aggregated across `deal.close.invoices`.
- `docs/vendor_roadmap.md` — Meta Graph + TikTok Display in v0.1; Phyllo for YouTube/LinkedIn/X/podcast/Substack in v2.

## Goal

Detect when deliverables go live, generate invoices automatically following the contract's payment schedule, get the agent to review and send, then track payment through to the deal's auto-archive into Phase 1.5 brand_deals.

Locked-in design decisions:
1. **Hybrid detection** — direct platform APIs (Meta Graph + TikTok in v0.1) poll for new posts; cron scores candidates against `posting_schedule[]`; agent confirms each match.
2. **Multi-invoice from v0.1** — LLM auto-parses the contract's `payment_terms` string into a structured `invoice_schedule[]`. Agent confirms once. Each entry fires its own `invoice_pack` when its trigger condition is met.
3. **Agency-wide invoice template** — captured in Phase 0 setup (single template for all talent + deals). Talent-specific billing entity pulled from `talent.billing_entity`. Brand-specific billing pulled from `contract_pack.context_snapshot.brand_legal_entity_at_gen`.
4. **v0.1 IG + TikTok direct; v2 expansion via Phyllo** — narrower API surface in v0.1; other platforms via agent manual URL entry until v2.
5. **Soft agent gate** — agent reviews rendered PDF before send; sending IS the approval (lighter than contract's legal review gate). Sent invoices are immutable — edits create a new version.

## Layer 1: Deliverable detection

### Polling cadence
- **Every 15 min** for IG Stories (24h ephemeral; can disappear before next poll)
- **Every 1 hour** for everything else (Reels, Feed Posts, Carousels, TikTok videos)
- Cron only polls deals in DELIVERY substages with unmatched `posting_schedule[]` entries — most deals don't poll most of the time

### Detection flow

```
Cron triggers (15 min for stories / 1 hour for others)
  │
  ▼ For each deal in DELIVERY-stage substages
  │  (content_in_production / pending_brand_approval /
  │  approved_for_posting / live / performance_window)
  │
  ▼ Skip if all posting_schedule[] entries have posted_at
  │
  ▼ For each unmatched deliverable:
  │  Query platform API for talent's recent posts since last poll
  │   · Instagram → Meta Graph API /me/media (talent's IG Business
  │     account; oAuth-connected at Phase 1 onboarding)
  │   · TikTok → TikTok Display API /video/list (talent's TikTok
  │     Business or Creator account; oAuth-connected at onboarding)
  │   · Other platforms (v0.1) → no auto-poll; agent enters URL manually
  │
  ▼ Score each candidate post against the deliverable:
  │  · time_window: posted within ±48h of scheduled_for     +40 pts
  │  · brand_handle: @brand_handle in caption/tags          +30 pts
  │  · campaign_hashtag: configured per-deal hashtag        +20 pts
  │  · content_type: matches deliverable.format             +10 pts
  │
  ▼ Confidence routing:
  │  ≥80   strong auto-suggest    → surface in agent UI prominently
  │  50-79 weak suggest           → surface with "uncertain" flag
  │  <50   log only               → audit trail; no UI surface
  │
  ▼ Agent reviews suggestions:
  │  · Confirm match → posting_schedule[i].posted_at + post_url set
  │     · posted_detection.method = "agent_confirmed_suggestion"
  │     · agent_confirmed_at + agent_confirmed_by set
  │  · Reject → posted_detection.agent_rejection_note logged;
  │     cron continues looking for better candidates
  │  · Enter URL manually → posted_detection.method = "manual_url_entry"
  │
  ▼ When ALL posting_schedule[] entries have posted_at:
  │  · Substage transitions to performance_window
  │  · Trigger evaluation runs for each invoice_schedule entry:
  │    if trigger_condition matches current deal state → fire invoice
```

### Match signal computation

| Signal | Detection logic |
|---|---|
| `time_window` | `abs(post.posted_at - scheduled_for) ≤ 48h` |
| `brand_handle` | Brand's @ handle (from `brand_candidate.social_handles`) appears in post caption, tagged users, or location |
| `campaign_hashtag` | Per-deal hashtag (captured at contract or first-detection time) appears in caption |
| `content_type` | Post format (reel/post/story/video) matches `deal.proposal.deliverables[].format` |

### Detection failure modes

| Failure | Behaviour |
|---|---|
| Talent posts but no signals match (no brand tag, no hashtag, wrong time) | Cron logs candidates with `match_score < 50` in `candidate_post_ids_considered`; agent can manually link the post via "I see it but the system missed it" UI flow |
| Talent posts to story; story expires before next poll | 15 min poll cadence catches most; missed stories require agent manual URL entry. Phyllo (v2) supports IG Stories webhook for real-time detection. |
| Multiple posts in the same time window match equally | All surfaced as candidates; agent picks the right one |
| Talent deletes + reposts | New posted_at supersedes old; old `posted_detection` archived to `candidate_post_ids_considered` |
| Brand handle changes mid-campaign | Brand handle refresh runs on `brand_candidate.social_handles` weekly; cron uses latest value |
| Talent's API token expires | Surface to agent + talent: "Reconnect [platform] to enable detection." Detection falls back to manual URL entry. |
| Deliverable scheduled but talent never posts (deal slipping) | After `scheduled_for + 14 days` with no posted_at, surface to agent: "Deliverable not detected — was it posted? Mark as delivered, push schedule, or escalate to talent." No auto-invoice fires. |

### Per-platform API notes (v0.1)

**Meta Graph API (Instagram):**
- Endpoint: `GET /{ig-user-id}/media?fields=id,caption,media_type,permalink,timestamp,username`
- Requires IG Business Account + Meta Business Suite connection (captured at talent onboarding `talent.platforms[]`)
- Rate limits: 200 calls/hour per user → trivial for our polling cadence
- Webhooks: supported for new media (v2 migration could move to webhooks instead of polling)
- Story media: separate endpoint `GET /{ig-user-id}/stories` (ephemeral, requires `instagram_manage_insights` permission)
- Env var: `META_APP_ID` + `META_APP_SECRET` (oAuth flow); per-talent tokens stored in talent profile

**TikTok Display API:**
- Endpoint: `GET /v2/video/list/` with `fields=id,title,video_description,create_time,share_url`
- Requires TikTok for Business or Creator account + oAuth scope `video.list`
- Rate limits: 100 calls/day per user (TIGHT — cron cadence may need adjustment for high-volume talent)
- Webhooks: not available in v0.1 Display API (paid Business API offers them)
- Env var: `TIKTOK_CLIENT_KEY` + `TIKTOK_CLIENT_SECRET`

Other platforms (YouTube, LinkedIn, X, podcast RSS, Substack RSS): v0.1 = manual URL entry; v2 via Phyllo unified API.

## Layer 2: Invoice generation

### Invoice schedule (one-time gate per deal)

On `deal.contract.contract_executed_at`, the orchestrator fires the **invoice schedule parse**:

1. **LLM input:** `contract_pack.commercial_proposal.llm_proposed.payment_terms` (free-text from agent at proposal time, e.g. "50% upon contract execution, 50% upon final delivery; NET-30")
2. **LLM output:** structured array of schedule entries with `sequence` / `percentage` / `trigger_condition` / `payment_terms_days` / `description`
3. **Compute `amount_usd`** per entry from `deal.proposal.fee_usd` × (percentage / 100)
4. **Agent gate:** UI shows proposed schedule with rationale; agent confirms (or edits — overrides logged). On confirm: `invoice_schedule[].schedule_confirmed_at` + `schedule_confirmed_by_agent_id` set; schedule locks.

The schedule is locked once confirmed. Subsequent contract amendments (via `deal.contract.amendment_log[]`) can trigger re-parse + re-confirm, but invoices already fired stay anchored to their original schedule.

### Invoice pack pipeline

Each schedule entry fires its own invoice pack when its `trigger_condition` is met. Pipeline is lighter than contract pack (most fields deterministic; 0-1 LLM passes).

```
Trigger fires (cron detects condition met OR agent manually fires)
  │
  ▼ STAGE A — Deterministic value extraction (no LLM)
  │  Schedule entry: percentage + amount_usd + description + payment_terms_days
  │  talent.billing_entity → FROM party (legal_name, address, tax_id, country)
  │  contract_pack.context_snapshot.brand_legal_entity_at_gen → TO party
  │  agency_profile.name + .branding → agency identification + logo
  │  agency_profile.invoice_template → numbering, tax, payment instructions
  │  Computed:
  │   · invoice_number (atomic increment + format from template)
  │   · issue_date (today)
  │   · due_date (issue + payment_terms_days, using calendar/business per template)
  │   · line_items[] (one per deliverable_ref, scaled by percentage)
  │   · subtotal/tax/total per template tax_handling
  │
  ▼ STAGE B — Optional LLM narrative (0-1 passes)
  │  If agency template has {{narrative_line_items}}:
  │   LLM drafts polished line descriptions
  │   ("2 Instagram Reels per campaign brief dated 2026-04-25,
  │     posted 2026-06-10 — 50% completion payment")
  │  If absent: literal "{format} × {count}" descriptions used
  │
  ▼ STAGE C — Compose markdown
  │  agency template + merge values + line_items table + amounts table
  │  + payment_instructions block → composed_markdown
  │
  ▼ STAGE D — Render
  │  composed.md → invoice.pdf (Puppeteer or pandoc)
  │  No Word artefact — invoices PDF-only by convention
  │
  ▼ STAGE E — Agent review (soft gate)
  │  Agent UI shows rendered PDF + key values summary
  │  Agent can edit any merge field / line item / amounts
  │   · Edits regenerate the PDF
  │   · Edits before send: same version (draft mutability)
  │   · Edits after send: create new version (sent invoices immutable;
  │     must void + reissue)
  │  Agent clicks "Send" → agent_review.sent_at + sent_by_agent_id +
  │   send_method set; payment_state.status: draft → sent;
  │   due_at computed from sent_at + payment_terms_days
  │
  ▼ Invoice sent
  │  v0.1: agent emails PDF manually; sent_to_email captured
  │  v2: Stripe Invoices / Xero API auto-send; external_invoice_id captured
```

### Invoice numbering atomic increment

`agency_profile.invoice_template.invoice_number_sequence` is a per-agency counter. On every new invoice_pack generation, generator atomically reads + increments. Format string applied: `INV-{YYYY}-{seq:04d}` → `INV-2026-0042`.

Per-agency (not per-talent, not per-deal) — numbering is contiguous across the whole agency for accounting integrity.

## Layer 3: Payment tracking

### v0.1 manual tracking

Each invoice_pack has its own `payment_state` block:
- `status` enum: `draft` / `sent` / `viewed_by_brand` / `paid` / `overdue` / `disputed` / `void`
- `due_at` computed at send time
- Agent manually sets `payment_received_at` + `payment_method` + `payment_amount_received_usd` + `payment_reference` when funds confirmed

### Overdue cron (v0.1)

Daily cron:
1. For each invoice_pack where `payment_state.status = sent` AND `due_at < now`:
   - Set `payment_state.status: overdue`
   - Append entry to `payment_reminder_log[]` with `type: agent_notification` + `days_overdue`
   - Send email to agent: "Invoice {invoice_number} for {deal_name} is {N} days overdue"
2. Reminder cadence: notification on day 1, then every 7 days thereafter
3. After 30 days overdue: suggest agent escalate (categorise as `disputed`, mark deal `loss.reason: unpaid`, write off, etc.) — agent decides

Agent appends their follow-up actions to `payment_reminder_log[]` with `type: agent_email_sent` / `phone_followup` / `escalation`. Audit trail of every reminder + response.

### Auto-archive interaction

Per the existing Phase 4 auto-archive trigger (`docs/deal_lifecycle_workflow.md` § Auto-archive on close):
- All schedule entries must have `invoice_pack_id` set (every invoice generated)
- All invoice packs must have `payment_state.status: paid`
- `final_kpis` must be populated
- `final_performance_report_attachment_id` must be set

When all conditions met: orchestrator sets `deal.close.all_invoices_paid_at` (computed: max of payment_received_at across all packs) and fires auto-archive into Phase 1.5 brand_deals. Per existing spec.

### v2 webhook integration

- **Stripe Invoices:** `invoice.paid` webhook → auto-populate `payment_received_at` + `payment_amount_received_usd` + `payment_reference` (Stripe charge ID) + `external_invoice_id` (Stripe invoice ID); `status` → `paid`
- **Xero / QuickBooks:** similar pattern; webhook on payment reconciliation
- **send_method enum** already supports `stripe_invoice_send` / `xero_send` / `quickbooks_send`
- v2 also enables `viewed_by_brand` status (Stripe webhook on `invoice.viewed`)

## Storage layout

```
data/deals/{deal_id}/
  prep_packs/                    # Phase 4.5
  proposal_packs/                # Phase 4.6
  contract_packs/                # Phase 4.7
  invoice_packs/                 # Phase 4.8 (NEW)
    seq1_v1.json
    seq1_v1_artifacts/{invoice.md, invoice.pdf}
    seq2_v1.json                 # second invoice (50% completion)
    seq2_v1_artifacts/{invoice.md, invoice.pdf}
    seq2_v2.json                 # revision after agent edit
    seq2_v2_artifacts/...
  context_uploads/               # shared across 4.6 + 4.7 + 4.8
```

All gitignored. File naming uses `seq{N}_v{M}` so the schedule sequence + version are visible in the filename.

## Integration touchpoints

| Existing piece | How Phase 4.8 plugs in |
|---|---|
| **Phase 0 `agency_profile.invoice_template`** | Single source of agency-wide template + numbering counter + tax settings + payment instructions. Captured at agency setup. |
| **Phase 0 `agency_profile.branding`** | Logo + colors applied to invoice PDF. Same single-source-of-truth pattern. |
| **Phase 1 `talent.billing_entity`** | FROM party on every invoice. Talent legal name, country, tax ID, address. |
| **Phase 1 `talent.platforms[]`** | API tokens for Meta Graph + TikTok Display polling. v0.1 onboarding flow needs to capture oAuth tokens during platform connection step. |
| **Phase 4.6 `deal.proposal.fee_usd` + `deliverables[]`** | Total deal fee + per-deliverable references for line items. |
| **Phase 4.7 `contract_pack.commercial_proposal.payment_terms`** | Source string for LLM schedule parsing. |
| **Phase 4.7 `contract_pack.context_snapshot.brand_legal_entity_at_gen`** | TO party on every invoice. |
| **`deal.delivery.posting_schedule[].posted_detection`** | Detection provenance from cron polling + agent confirmation. Each invoice pack's `context_snapshot.matched_posts[]` references these. |
| **`deal.close.invoice_schedule[]`** | LLM-parsed payment plan with one-time agent gate. Locks after confirmation. |
| **`deal.close.invoice_pack_ids[]`** | Flat FK list to all invoice pack versions ever generated. |
| **`deal.close.all_invoices_paid_at`** | Computed; gates auto-archive. |
| **Phase 4 deal lifecycle (CLOSE substages)** | `invoice_sent` substage = at least one invoice pack with status `sent`. `invoice_paid` = all schedule entries with `payment_state.status: paid`. Substage transitions driven by aggregate state across all invoices. |

## Failure handling (consolidated)

| Failure | Behaviour |
|---|---|
| LLM parse of payment_terms produces non-sensical schedule | Agent gate catches; agent edits or re-parses. Schedule cannot lock without agent confirm. |
| Sum of schedule percentages ≠ 100% | Validation rejects on confirm; surface to agent. |
| Trigger condition fires but invoice_pack generation fails | Retry 3x; on final failure log to deal + notify agent. Schedule entry stays `fired_at: null` — next cron retries. |
| Agent edits sent invoice | Reject edit on the same version (sent invoices immutable). Offer "Void + reissue" UI: void current invoice + generate v(N+1) for the same schedule sequence. Original PDF retained for audit. |
| Brand pays wrong amount (over/under) | Agent sets `payment_amount_received_usd` to actual amount + `reconciliation_note`. If under, `status` stays `sent` until shortfall resolved or written off. If over, `status: paid` + note. |
| Brand disputes invoice | Agent sets `status: disputed` + reconciliation_note. Pause overdue cron until resolved. |
| Detection cron suggests wrong post repeatedly | Agent rejection log over multiple cycles trains a per-deal exclusion list. v0.2: feedback into match scoring. |
| Platform API token expires mid-deal | Surface "Reconnect" prompt to talent + agent; detection falls back to manual URL entry until reconnected. |
| Talent has multiple IG accounts; cron polls wrong one | `talent.platforms[]` resolution at onboarding captures the specific IG Business Account ID for the campaign account, not the talent's personal account. |
| FX adjustments (deal in EUR, paid in USD) | `amounts.currency` + `fx_rate_to_usd` captured at generation. Agent reconciles actual received vs invoice amount in `reconciliation_note`. |

## Cost profile

**Per-pack LLM cost:** $0.05-0.15 per invoice (much lighter than contract — mostly deterministic, often 0 LLM passes).
**Per-deal LLM cost:** one schedule parse on contract execution (~$0.02) + one per invoice pack generation.
**Platform API costs (v0.1):** Meta Graph free; TikTok Display free.
**Phyllo (v2):** ~$50-200/creator/month for unified API across YouTube/LinkedIn/X/podcast.

## v0.1 explicit non-goals

- **Phyllo / unified creator API.** v0.1 = direct platform APIs for IG + TikTok only. v2 adds Phyllo for YouTube/LinkedIn/X/podcast/Substack.
- **Auto-send invoices.** v0.1 = agent reviews + manually emails. v2 = Stripe Invoices / Xero / QuickBooks API send.
- **Real-time payment notifications.** v0.1 = manual `payment_received_at` set by agent. v2 = webhook from accounting integration.
- **Automated payment reminders to the brand.** v0.1 = cron notifies agent; agent writes the follow-up themselves. v2 = agency-configurable auto-reminder emails.
- **Multi-currency support beyond USD-normalisation.** v0.1 = invoices in USD; non-USD captured via `currency` + `fx_rate_to_usd` but no rendering of multi-currency invoices.
- **Tax jurisdiction logic.** v0.1 = single `default_tax_rate` per agency. v2 = per-deal jurisdiction rules (UK VAT vs US sales tax vs no tax based on brand country).
- **Partial payment scheduling.** v0.1 = each schedule entry is a single payment. v2 could split a single schedule entry into installments.

## v0.2 open questions

1. **Detection signal tuning** — agent rejection patterns should feed back into the scoring algorithm. Per-deal exclusion lists. v0.2.
2. **Auto-reminder to brand** — when invoice goes overdue, auto-send a polite reminder email (with agent approval before each send, or fully autonomous). v0.2.
3. **Pre-bill notifications** — N days before trigger condition fires, surface "About to generate invoice X — review schedule entry?" to agent. Avoids surprise invoices.
4. **Per-jurisdiction tax handling** — UK VAT, US sales tax (per state), EU reverse-charge, no-tax (B2B export). v0.2.
5. **Stripe Connect for marketplace** — if agency runs talent's bank accounts via Stripe Connect, invoice → talent's connected account flow. v0.2.
6. **Late fee auto-calculation** — overdue invoices accrue late fees per statutory rates. v0.2.
7. **Credit notes** — when an invoice is voided or partial refund issued, generate a credit note (negative invoice) for accounting. v0.2.
8. **Brand-side payment portal** — link in the invoice PDF takes brand to a payment landing page (Stripe Checkout / agency-branded). v0.2 with Stripe.
