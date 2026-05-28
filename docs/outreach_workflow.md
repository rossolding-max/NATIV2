# Outreach Workflow (Phase 3b)

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the AI-generated cold-outreach engine that takes a qualified brand contact and runs a multi-step email sequence with reply detection and full per-email analytics.

**Pairs with:**
- `docs/contact_enrichment_workflow.md` (Phase 3a) — produces the named contacts this workflow pitches.
- `docs/brand_discovery.md` (Phase 2) — produces the brand candidates that trigger contact enrichment, which triggers outreach.
- `docs/vendor_roadmap.md` — Smartlead confirmed as v0.1 send/sequence backend.
- `schemas/pitch_angle.schema.json` + `data/pitch_angles.json` — the angles library the AI draws from.
- `schemas/pitch_template.schema.json` — sequence templates (structure, not content).
- `schemas/pitch_enrollment.schema.json` — running instance of a template for a specific (talent, contact) pair.

## Goal

For every qualified brand contact, run a personalised multi-step outreach sequence with:
- AI-generated per-step content (Claude Sonnet for first touch; Haiku for follow-ups)
- Per-contact angle selection from the curated library
- Real-time reply detection → kill across all sequences for that contact
- Full per-email analytics provenance (which angles used, which model, what engagement, what outcome)
- Per-talent sender domain (deliverability + authenticity)

**Ultimate objective:** signed brand deals. Every metric in this workflow rolls up to that — reply rate is the v0.1 headline metric because it's the most reliable leading indicator of conversion.

**Scope note — v0.1 is email-only.** LinkedIn outreach (DMs, InMails, connection requests) is **deferred to v2**. The schemas, templates, and orchestrator all reject non-email channels at v0.1. LinkedIn API is still used in Phase 3a for contact verification and enrichment (see `docs/contact_enrichment_workflow.md`) — that's a separate use case from sending LinkedIn messages.

**Sender model — agency, not talent.** Outreach is sent by the talent's **agency** in the agent's name (e.g. `sarah@nativeagency.com`). Voice: **agent-led on-behalf-of talent** — "I'm Sarah from Native Agency — I represent Jane Doe, who drove 1.24M reach for Gymshark." See `docs/agency_setup_workflow.md` (Phase 0) for the one-time agency identity + sender mailbox + DNS + warmup setup. v0.1: single agent, single agency. v2: multi-agent within one agency.

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│ Contact enriched + qualified (Phase 3a)                            │
│   contact.decision_role classified                                 │
│   contact.qualification.tier in [qualified, speculative]           │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP A: Template selection                                          │
│   contact.decision_role → pitch_template (1 default per role)      │
│   Agency may override with custom template                          │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP B: Angle evaluation                                            │
│   For each angle in data/pitch_angles.json:                         │
│     evaluate trigger.type against (talent, contact, brand) context │
│   → list of APPLICABLE angles + merge field values                  │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP C: Per-step AI generation (loop over template.steps[])        │
│   Inputs: talent + contact + brand + step.intent + applicable      │
│           angles + previous-step content (for follow-ups) + step's │
│           preferred/excluded angle categories                       │
│   Output: subject + body + angles_used + full provenance           │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP D: Review queue (default ON in v0.1)                           │
│   Talent / agency sees generated content per step before send       │
│   Approve all → push to Smartlead                                   │
│   Edit any → AI re-runs that step with edit as guidance             │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP E: Smartlead campaign push                                     │
│   Create/use Smartlead campaign per (talent, template)              │
│   Send from talent's own domain mailbox                             │
│   Schedule per template step timings (day 0, +3, +7, +14)          │
└────────────────────────────┬───────────────────────────────────────┘
                             │
              Smartlead webhooks (real-time)
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP F: Engagement event handling                                   │
│   sent / delivered / opened / clicked / replied / bounced /         │
│   unsubscribed → log to enrollment.steps[].engagement_events[]      │
│   Refresh engagement_summary aggregates                             │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼ (if replied)
┌────────────────────────────────────────────────────────────────────┐
│ STEP G: Reply classification + kill                                 │
│   Claude Haiku classifies reply intent:                             │
│     interested / declined / out_of_office / unrelated /             │
│     unsubscribe_request / needs_more_info / wrong_person_routed     │
│   → kill THIS enrollment + all other active enrollments for         │
│     the same contact across the roster                              │
│   → if interested: surface in talent UI as hot lead                 │
│   → if OoO: pause + auto-resume after `ooo_until`                   │
│   → if unsubscribe_request: contact.do_not_contact = true forever   │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ STEP H: Analytics aggregation (scripts/analyze_outreach.py)         │
│   Rolls every step record up into A/B slices: by angle, by         │
│   decision_role, by template, by brand_tier, by send_time, etc.    │
│   Output: data/outreach_analytics/aggregates_*.json                │
│   v0.1: output only; user reviews + edits angles manually           │
│   v2:   auto-updates pitch_angles.json strength_scores              │
└────────────────────────────────────────────────────────────────────┘
```

## Triggers

| Trigger | When |
|---|---|
| **Auto-enrol on qualified contact** | Phase 3a contact enrichment writes a contact with `qualification.tier ∈ [qualified, speculative]` AND `do_not_contact == false` AND no active enrollment exists. Default ON; configurable per-talent. |
| **Manual** | User selects a contact (or set) from the brand_candidates UI and clicks "Add to sequence". Picks template + reviews content. |
| **Re-engagement schedule** | Phase 2 Search 1 (re-engagement) surfaces an eligible past brand. The talent's existing relationship gets a `past_relationship_eligible` angle pre-selected. |

## Template selection (Step A)

`contact.decision_role` maps 1:1 to a default template:

| decision_role | Default template | Customisable? |
|---|---|---|
| `buyer` | `buyer-direct-pitch` (4 steps: day 0, +3, +7, +14) | Yes, per agency/talent |
| `influencer` | `influencer-warm-intro` (3 steps: day 0, +5, +12) | Yes |
| `champion` | `champion-activation` (2 steps: day 0, +7) | Yes |
| `gatekeeper` | **No auto-sequence** — surfaced for manual handling in UI (too brittle for full automation) | Manual only |
| `unknown` | Fallback to `buyer-direct-pitch` | Yes |

Templates live at `data/pitch_templates/{template_id}.json`. The three default templates ship in repo with the v0.1 build.

### Default template — `buyer-direct-pitch`

```jsonc
{
  "template_id": "buyer-direct-pitch",
  "name": "Buyer — direct pitch",
  "target_decision_role": "buyer",
  "guardrails": {
    "max_body_chars": 600,
    "max_subject_chars": 60,
    "tone": "direct_professional"
  },
  "steps": [
    {
      "step_number": 1,
      "intent": "first_touch_strongest_angle",
      "timing_offset_days": 0,
      "channel": "email",
      "ai_model_override": "claude-sonnet-4-7",
      "preferred_angle_categories": ["competitive_proof", "similar_talent_precedent", "re_engagement"]
    },
    {
      "step_number": 2,
      "intent": "follow_up_different_angle",
      "timing_offset_days": 3,
      "channel": "email",
      "ai_model_override": "claude-haiku-4-5",
      "preferred_angle_categories": ["demographic_match", "niche_fit", "brand_momentum"],
      "excluded_angle_categories": ["competitive_proof"]
    },
    {
      "step_number": 3,
      "intent": "follow_up_with_creative_concept",
      "timing_offset_days": 7,
      "channel": "email",
      "ai_model_override": "claude-haiku-4-5",
      "preferred_angle_categories": ["creative_concept", "performance_proof"]
    },
    {
      "step_number": 4,
      "intent": "break_up_door_open",
      "timing_offset_days": 14,
      "channel": "email",
      "ai_model_override": "claude-haiku-4-5"
    }
  ]
}
```

### Default template — `influencer-warm-intro`

Similar shape, 3 steps, `tone: warm_casual`, preferred_angle_categories favour `mutual_connection`, `brand_momentum`, `role_default` (the `influencer_strategic_intro` always-on angle).

### Default template — `champion-activation`

2 steps, `tone: warm_casual`, leads with `role_default.champion_advocacy_ask` + supporting `mutual_connection` angles. Asks for internal advocacy or warm intro, NOT a deal.

## AI generation (Step C) — the core mechanic

For each step in the template, the LLM is given:

1. **System prompt** (template-driven):
   - **Sender context** from `data/agency_profile.json`: the agent's name + title, agency name, voice mode (`agent_led_on_behalf_of_talent` by v0.1 default). LLM instructed: "You are {agent_name}, writing on behalf of {talent_name}. Refer to the talent in third person. Open with a brief self-introduction; the body cites the talent's track record."
   - The talent's identity + voice profile (used as factual context about whom the agent represents; NOT the speaking voice)
   - The step's `intent` (what this email is for)
   - Template `tone` + guardrails (max_body_chars, must-include unsubscribe, etc.)
   - The 5–10 applicable angles for this (talent, contact, brand) combo, with their `example_phrasing` patterns (which already use `{talent_name}` references reflecting the agent-led voice)
   - The step's `preferred_angle_categories` (LLM should lean toward these) and `excluded_angle_categories` (must avoid)
   - Signature template from `agency_profile.default_signature_template` (LLM appends this verbatim; validation ensures `{unsubscribe_link}`, `{agency_address}`, `{agent_name}` tokens are present)

2. **User-message context**:
   - Full talent profile JSON (excluding sensitive fields)
   - Full contact record (name, title, function, seniority, decision_role, location, tenure)
   - Brand record + brand_snapshot
   - **Citation material from `data/brand_deals/{talent_id}.json`** — relevant past-deal records (filtered to same-industry, same-competitor-set, or same-brand-if-re-engaging). Each deal contributes KPIs with source provenance; the LLM prefers higher-confidence sources (`platform_verified` > `brand_reported` > `third_party`) when picking which figure to cite. Powers the 5 new `past_campaign_*` angles + enriches `past_brand_direct_competitor`, `past_relationship_eligible`, and `case_study_available`.
   - Previous-step content (for follow-ups, to ensure variation)
   - Engagement signals so far (opened the previous one? clicked anything?)

3. **Required output format** (enforced via JSON mode):
   ```jsonc
   {
     "subject": "...",
     "body": "...",
     "angles_used": {
       "primary": "past_brand_direct_competitor",
       "supporting": "iab_demographic_overlap"
     },
     "personalization_fields_used": ["contact.name.first", "competitor_brand", "campaign_metric"],
     "reasoning": "Selected past_brand_direct_competitor because talent has Lululemon in previous_brands and Alo Yoga is a curated competitor. Supporting with demographic match because 71% female 25-34 aligns with Alo's primary target."
   }
   ```

4. **Validation post-LLM**:
   - JSON schema check (must match expected shape)
   - Length checks (subject ≤ max_subject_chars; body ≤ max_body_chars)
   - Merge-field check (every field listed in `personalization_fields_used` must actually appear in the body)
   - Angle check (primary + supporting both exist in `data/pitch_angles.json`)
   - Tone check (LLM-self-evaluation: does this match the template tone?)
   - Banned-phrase check: must NOT contain canned cold-email tells ("hope this email finds you well", "I wanted to reach out", "circling back" at step 1, etc.)
   - Failed validation → regenerate up to 3 times; on persistent failure, queue for human-only review.

5. **Token economics:**
   - Step 1 (Sonnet 4.7): ~8k input + 300 output tokens = ~$0.024/email
   - Steps 2–4 (Haiku 4.5): ~5k input + 250 output tokens = ~$0.001/email each
   - **Full 4-step sequence: ~$0.027/contact**
   - 100 contacts × full sequence = ~$2.70 in Claude costs. Affordable at any reasonable scale.

## Review-before-send queue (Step D)

Every generated step waits in a review queue before going to Smartlead. The talent (or agency manager) sees:

- All steps in the sequence at once (so they see the full arc)
- Each step's: subject, body, scheduled date, angle_used, reasoning
- Edit-in-place (which triggers AI re-generation with the edit as guidance)
- Approve-all (or per-step) → pushes to Smartlead

### Hard rule: step 1 always requires human approval

**Step 1 (the first touch) MUST be reviewed and approved by the user before sending. No auto-approve for the first email, ever — across every talent, every template, every version.** This is a non-configurable invariant of the system.

Why it's locked:
- First email is the highest-stakes — it's what the recipient sees first, sets the relationship tone, and once sent can't be unsent
- Reply rates are driven disproportionately by step 1; a bad first impression poisons the whole sequence
- The AI is genuinely good but never above oversight on the touch that matters most
- Edge cases (the contact is a personal friend; the brand had a recent PR crisis the AI didn't catch; tone is slightly off for the talent's voice) are exactly what humans catch and AI doesn't

Orchestrator behavior:
- Step 1 enters `awaiting_approval` state and stays there until explicit user approval
- The enrollment cannot transition to `active` while step 1 is unapproved
- Cron jobs / batch approvals never auto-clear step-1 reviews — they require a per-step user action (or at minimum an "approve all in review queue" click)

### Steps 2+ (follow-ups)

For follow-ups, auto-approval is **configurable per-talent in v0.2**. Recommended posture: keep review-first for the talent's first 2–3 weeks of outreach (~50–100 sequences), then flip auto-approve on for follow-ups if the talent is confident in the output. Step 1 remains manual regardless.

Auto-approve guardrails for follow-ups (when enabled in v0.2):
- Skip auto-approve if the generated content scored low on the post-LLM validation pass
- Skip auto-approve if the generated content materially diverges from the talent's prior approved tone (per a similarity check against previously-approved emails)
- Skip auto-approve if the brand has surfaced a `sensitive_category` warning since the last step

## Smartlead integration (Step E)

**Campaign model:** one Smartlead campaign per (talent, template) combination.
- e.g. `jane-doe-talent::buyer-direct-pitch` is one campaign
- All enrollments using that template for that talent become leads in that campaign

**Lead push:** for each approved enrollment:
```
POST /api/v1/campaigns/{campaign_id}/leads
{
  "lead": {
    "email": "{contact.email.address}",
    "first_name": "{contact.name.first}",
    "last_name": "{contact.name.last}",
    "company_name": "{brand.name}",
    "custom_fields": {
      "enrollment_id": "{enrollment_id}",
      "decision_role": "{contact.decision_role}",
      "primary_angle": "{step_1.generation_meta.angles_used.primary}"
    }
  },
  "sequence": {
    "subject_1": "{step_1.generated_content.subject}",
    "body_1":    "{step_1.generated_content.body}",
    "subject_2": "{step_2.generated_content.subject}",
    "body_2":    "{step_2.generated_content.body}",
    ...
  },
  "scheduled_send_at": "{enrollment.scheduled_start_at}"
}
```

Smartlead handles from there: send schedule per step, mailbox warmup pacing, open/click tracking pixels, reply detection from the talent's mailbox.

## Webhook handling (Step F)

We register Smartlead webhooks for:

| Event | Action in our app |
|---|---|
| `email_sent` | Update `enrollment.steps[N].status = "sent"` + `sent_at` |
| `email_delivered` | Append to `engagement_events[]` |
| `email_opened` | Append to `engagement_events[]`; infer `likely_mpp` from User-Agent + timing |
| `email_clicked` | Append; capture URL |
| `email_replied` | Append + trigger Step G (reply classification + kill) |
| `email_bounced` | Append; if hard: set `contact.email.verification_status = "bounced"`, kill enrollment |
| `email_unsubscribed` | Append; set `contact.do_not_contact = true` + `opt_out_at = now`; kill all enrollments for this contact |

Daily reconciliation cron polls Smartlead for any missed events.

## Reply classification + kill (Step G)

When `email_replied` fires:

1. Claude Haiku reads the reply body. Single classification call:
   ```
   Classify this reply to a cold pitch. Outcome is ONE of:
     interested | declined | out_of_office | unrelated |
     unsubscribe_request | needs_more_info | wrong_person_routed

   Extract structured signals:
     asked_for_pricing: bool
     asked_for_meeting: bool
     asked_for_more_info: bool
     objections_raised: string[]
     next_step_proposed: string
     ooo_until: date (if out_of_office)
     routed_to_contact: string (if wrong_person_routed)
   ```

2. Update `enrollment.steps[N].outcome_classification`.

3. **Kill logic:**
   - `interested` → kill this enrollment; **create a Phase 4 deal in `stage: "lead"`** (per `docs/deal_lifecycle_workflow.md`) with `originating_enrollment_id` + `originating_decision_role_at_pitch` (snapshot from contact at pitch time, anchors won-deal-by-role analytics) set; UI surfaces as hot lead; agent gets notified. If `extracted_signals.asked_for_meeting == true`, the deal pre-seeds at `substage: "initial_call_scheduled"` instead of `new_lead`. **Bidirectional link:** the orchestrator also writes the new deal's id back to `pitch_enrollment.created_deal_id` so anyone reviewing the enrollment can navigate forward to the resulting deal.
   - `declined` → kill this enrollment; consider `do_not_contact: true` (manual or auto based on tone)
   - `out_of_office` → pause enrollment until `ooo_until + 1 day`, then auto-resume
   - `unrelated` → kill this enrollment only (don't penalize contact)
   - `unsubscribe_request` → set `contact.do_not_contact = true` + `opt_out_at`; kill ALL enrollments for this contact across the roster
   - `needs_more_info` → kill this enrollment, surface for talent to reply manually
   - `wrong_person_routed` → kill, capture `routed_to_contact`, optionally start enrollment for the routed person

4. **Cross-roster kill:** also kill any OTHER active enrollment for this same `contact_id` from a different talent. Single reply = stop the spam from us across the board.

## Analytics aggregation (Step H)

`scripts/analyze_outreach.py` runs weekly (or on-demand). Loads every `data/pitch_enrollments/*.json` and rolls into aggregates.

**Sliceable dimensions:**

| Dimension | Why |
|---|---|
| Primary angle | "Which angle has the best reply rate?" |
| Primary × supporting angle pair | "Does pairing X with Y beat X alone?" |
| Angle × decision_role | "Which angles work for buyers vs influencers?" |
| Angle × brand_tier (typical_campaign_tier) | "Does competitive proof work at premium brands the same as mid?" |
| Step number | "When in the sequence do replies happen?" |
| Template | "buyer-direct-pitch vs influencer-warm-intro reply rate?" |
| Talent | "Which of our roster has the highest reply rate?" |
| Brand industry | "Do activewear brands respond better than fintech?" |
| Send time of day | "Tuesday 10am vs Friday 4pm?" |
| Send day of week | "Mid-week vs Friday?" |
| Subject pattern (length, ?, emoji) | "Question subjects vs declarative?" |
| Sender domain (if multi-domain test) | "Which talent domain has the best inbox placement?" |

**Metrics computed per slice:**

| Metric | Formula |
|---|---|
| Sent | count(step.status = "sent") |
| Delivery rate | delivered ÷ sent |
| **Reply rate (HEADLINE)** | replied ÷ delivered |
| Positive reply rate | outcome_classification.outcome="interested" ÷ delivered |
| Human open rate | human_opens ÷ delivered (MPP-filtered) |
| Raw open rate | opens_total ÷ delivered (shown but flagged as noisy) |
| Click rate | unique_clicks ÷ delivered |
| Bounce rate | bounced ÷ sent |
| Unsubscribe rate | unsubscribed ÷ delivered |
| Mean time-to-reply | avg(time_to_reply_seconds) over replied=true |
| Cost per positive reply | sum(generation_meta.cost_usd) ÷ count(interested) |

**Output:** `data/outreach_analytics/` (gitignored) — one file per dimension:
- `aggregates_by_angle.json`
- `aggregates_by_decision_role.json`
- `aggregates_by_template.json`
- `aggregates_by_brand_tier.json`
- `aggregates_by_send_time.json`
- `aggregates_by_talent.json`
- ... etc.

**v0.1 explicit non-goal:** the analyzer does NOT auto-update `pitch_angles.json` `authored_strength_score`. Output is for human review. Users edit angles manually as they learn. Closed-loop auto-tuning is a v2 goal.

## Agency-level sender setup (not per-talent)

**Per the v0.1 architecture:** outreach emails are sent by the talent's **agency**, not by the talent themselves. The agency configures sender identity **once** during Phase 0 (`docs/agency_setup_workflow.md`); all subsequent talent onboarding plugs into the pre-warmed agency mailbox.

**v0.1 model — single agent / single agency:**
- One sending mailbox per agency: typically `{agent_first_name}@{agency_domain}` (e.g. `sarah@nativeagency.com`)
- One agent represents all talents in the roster
- Voice: **agent-led on-behalf-of talent** ("I'm Sarah from Native Agency — I represent Jane Doe, who drove 1.24M reach for Gymshark...")
- All 42 pitch angles' `example_phrasing` patterns use this voice; `{talent_name}` is a required merge field

**Why agency-level (not per-talent):**
- **Cost** — Smartlead drops from ~$94/mo per talent to ~$94/mo for the whole agency
- **Setup** — DNS records + warmup is a one-time cost, not repeated per onboarding
- **Reply handling** — all replies land in the agency's inbox; the agent triages across the roster (rather than each talent receiving replies for their own deals)
- **Authenticity for the brand** — they recognise the agent as a real human partnerships professional, not a marketing-platform-as-talent

**DNS records** (set during agency setup):
- **SPF** — TXT record: `v=spf1 include:smartlead.io ~all`
- **DKIM** — TXT record provided by Smartlead per-domain
- **DMARC** — TXT record: `v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@{agency_domain}`

**Warmup** — Smartlead's peer-to-peer warmup network builds sender reputation over 2-4 weeks. Talent onboarding can run in parallel; outreach is blocked until `sending_mailboxes[].warmup_status == "complete"`.

**v2 expansion (deferred):** multi-agent rosters. The schema (`schemas/agency_profile.schema.json`) is already array-shaped for `agents[]` and `sending_mailboxes[]`; v0.1 simply constrains `agents` to `maxItems: 1`. v2 lifts the constraint, adds per-agent mailbox warmup, and routes outreach by `agents[].represents_talent_ids[]`.

## State machine

```
ENROLLMENT LIFECYCLE:

  Contact qualifies                  drafted (no review needed yet)
        │                                  │
        ▼                                  ▼
   ┌─────────┐    AI generates    ┌────────────────────┐
   │ drafted │ ─────────────────▶ │ awaiting_approval  │
   └─────────┘                    └─────┬──────────────┘
                                        │
                          user approves  │  user kills
                                        ▼  │
                                 ┌─────────┐ │
                                 │ active  │◄┘
                                 └────┬────┘
                                      │
              ┌───────────────────────┼──────────────────────┐
              │                       │                      │
        last step sent           reply received        bounce / unsubscribe
              │                       │                      │
              ▼                       ▼                      ▼
         ┌──────────┐            ┌────────┐             ┌────────┐
         │completed │            │ killed │             │ killed │
         └──────────┘            └────────┘             └────────┘
                                      │
                              outcome=interested
                                      │
                                      ▼
                              [Hot lead in UI;
                               talent replies
                               manually from here]
```

## Failure handling

| Failure | Behaviour |
|---|---|
| LLM generation fails or returns invalid JSON | Retry 3 times with exponential backoff; on persistent failure, surface to manual queue |
| LLM generates content with banned phrases | Retry with explicit "avoid these phrases" reinforcement; on persistent failure, manual queue |
| Smartlead API down at send time | Queue locally; cron retries every 30 min; alert ops if down > 1 hour |
| Smartlead webhook delivery missed | Daily reconciliation poll (`GET /campaign/{id}/leads/{lead_id}/events`) picks up gaps |
| Sending domain warmup incomplete | Block send; surface in UI "Your domain is still warming up (~5 days remaining)" |
| Talent mailbox suspended (spam complaints) | Pause all active enrollments for that talent; alert; manual investigation required |
| LLM classifies reply as `unsubscribe_request` but reply was actually positive | User can override classification in the UI — `outcome_classification.user_corrected_to = "interested"` |
| Reply received on enrollment already killed | Log + ignore (race condition between webhook + kill action) |
| Cross-roster kill missed an active enrollment (two talents pitching same contact) | Daily reconciliation: check every `do_not_contact: true` contact for active enrollments; force-kill any found |

## Costs at scale (estimated, monthly)

For a 10-talent roster with each talent running ~50 active enrollments per month (full 4-step sequence):

| Vendor | Item | Cost |
|---|---|---|
| Smartlead | Pro tier per talent (1 mailbox each) | $94 × 10 = $940 |
| Claude | Generation (~$0.027 × 500 enrollments) | ~$14 |
| Claude | Reply classification (~$0.001 × 200 replies, est.) | ~$0.20 |
| Domain | Annual registration if new (10 × $12) | $120/year = $10/mo |
| **Total** | | **~$965/mo for 10 talents = ~$97/talent/mo** |

Compares favourably to e.g. dedicated agencies charging $2,500+/mo for cold outreach as a service.

## M9 implementation notes (shipped vs deferred)

M9 v0.1 ships the **complete generation → real outreach → reply →
deal-creation chain** described above. No schema migration: the M1
``pitch_template`` / ``pitch_angle`` / ``pitch_enrollment`` / ``deal``
tables + Pydantic codegen + M3 Smartlead client + M3 HMAC webhook helper
all reused as-is.

**Shipped:**

| Layer | Module / file |
|---|---|
| 3 default templates | ``data/pitch_templates/{buyer-direct-pitch,influencer-warm-intro,champion-activation}.json`` |
| 42-angle library + seed | ``data/pitch_angles.json`` (pre-authored); ``scripts/seed_pitch_angles.py`` + ``scripts/seed_pitch_templates.py`` idempotent importers |
| Template selector (decision_role → template) | ``app/services/outreach/template_selector.py`` |
| Angle filter (13 high-signal triggers; rest fail-soft to False) | ``app/services/outreach/angle_filter.py`` |
| Per-step LLM generator (Opus step 1, Haiku steps 2+; ≤3 retries on validation failure) | ``app/services/outreach/step_generator.py`` |
| Policy filter (DNC + active-enrollment + 14-day cross-talent cooldown) | ``app/services/outreach/policy_filter.py`` |
| Loopback writers (``brand_contact.pitch_history[]``, ``brand_deal.last_re_engagement_pitch_date``) | ``app/services/outreach/loopback_writers.py`` |
| Orchestrator (persists in ``awaiting_approval`` per Step-1 manual gate) | ``app/services/outreach/orchestrator.py`` |
| Smartlead push (find-or-create campaign + add lead + push sequence) | ``app/services/outreach/smartlead_push.py`` |
| Reply classifier (Haiku, 7 outcomes, structured signals, fail-soft) | ``app/services/outreach/reply_classifier.py`` |
| Deal creator (GAP-06 bidirectional FK in single DB transaction) | ``app/services/outreach/deal_creator.py`` |
| Webhook reply pipeline (classify → side-effect routing) | ``app/services/outreach_reply_handler.py`` |
| JSON snapshot writer (current + immutable runs/) | ``app/services/outreach/snapshot.py`` |
| Celery task: generation | ``app/services/outreach_generation_task.py`` |
| Celery beat task: 5-min state sync | ``app/services/enrollment_state_sync.py`` |
| REST router (7 endpoints, 3 routers) | ``app/api/enrollments.py`` |
| Smartlead webhook receivers (email_event + reply, HMAC + Redis dedup 24h TTL) | ``app/api/webhooks/smartlead.py`` |

**Locked v0.1 decisions:**
- **Manual trigger only.** Auto-enroll from M8 is OFF in v0.1; flip ON in M9.1 once we measure reply rate + cost-per-run on real campaigns.
- **One Smartlead campaign per (talent, template).** Up to 3 campaigns per active talent.
- **Step-1 manual approval is permanent.** Every Step-1 email goes to the review queue; agent clicks ``POST /enrollments/{id}/approve`` to release.
- **Email channel only.** Schema ``channel`` enum locked to ``email``; LinkedIn DM/InMail/connection defer to v2.
- **3 templates ship; gatekeeper is manual.** Gatekeeper-classified contacts surface a UI badge but no auto-template.
- **LLM tiers per spec.** Step-1 generation = Opus 4.7; Steps 2+ = Haiku 4.5; reply classifier = Haiku 4.5.

**Deferred to M9.1+:**
- Auto-enroll on M8 qualified/speculative contacts.
- Auto-approve for follow-up Steps 2+ (Step 1 stays permanently manual).
- Closed-loop angle strength tuning from reply-rate analytics.
- Multi-step engagement branching.
- A/B testing infrastructure.
- Reply auto-draft for human review.
- Calendar booking integration on interested + asked_for_meeting.
- Bounce-rate template throttling.
- Talent voice profile (currently inferred from ``talent.bio``).
- Smartlead campaign segmentation by vertical for warmup optimisation.

**Trigger surfaces in v0.1:**
- ``POST /api/v1/talents/{talent_id}/outreach-generation/run`` — Celery enqueue with body ``{"contact_id": "...", "brand_id": "...", "template_id?": "..."}``.
- ``POST /api/v1/enrollments/{enrollment_id}/approve`` — Step-1 release + inline Smartlead push.
- ``POST /api/v1/enrollments/{enrollment_id}/kill`` — manual kill (records reason).
- ``POST /api/v1/webhooks/smartlead/email_event`` + ``POST /api/v1/webhooks/smartlead/reply`` — Smartlead-driven (HMAC verified).

---

## Open questions for v0.2 / v0.3

1. **LinkedIn outreach channels (v2)** — **explicitly deferred from v0.1.** The schema currently restricts `channel` to `email` only. When v2 ships LinkedIn-send integration, the enum will re-add `linkedin_message` / `linkedin_inmail` / `linkedin_connection` and the orchestrator will route those steps through whichever LinkedIn-send vendor is chosen at that time. v0.1 to v2 transition involves: vendor selection (LinkedIn's official Sales Navigator API vs third-party like Closely / Expandi / La Growth Machine), automation-policy review (LinkedIn's anti-automation enforcement is aggressive), and per-talent LinkedIn account warmup. None of these are blockers for v0.1 — email-only ships now.
2. **Auto-approve for follow-ups** — **step 1 is permanently manual-only** (locked guardrail). For follow-ups (steps 2+), v0.2 will add per-talent auto-approve configuration with the three guardrails above (validation score, tone-similarity, fresh sensitive flag).
3. **Closed-loop angle tuning** — `pitch_angles.json` strength_scores currently human-edited. v2: analyzer auto-updates scores based on observed reply rates (with sample-size + variance guards).
4. **Smartlead campaign segmentation** — v0.1 = one campaign per (talent, template). v0.2 may need finer segmentation (e.g. one campaign per (talent, template, brand_industry) for sender-warmup-by-vertical).
5. **Reply auto-response** — currently a reply triggers kill + manual handoff. v0.2 could draft a reply for the talent to review (similar to Instantly's AI Reply Agent feature).
6. **Multi-step branching** — templates support `branching` config in the schema but v0.1 doesn't fully implement it. v0.2 wires up engagement-based step-skipping (e.g. if step 1 was clicked, skip step 2 and go to creative_concept step 3 immediately).
7. **Talent voice profile** — each talent has a writing voice. We currently rely on the LLM picking up tone from `talent.bio`. v0.2: a structured `talent.voice_profile` field with sample writing the LLM uses for style matching.
8. **A/B testing infrastructure** — v0.2: explicit A/B test definition where two templates run against the same contact pool with random assignment, results compared in the analytics layer.
9. **Bounce-rate-based template throttling** — if any template's bounce rate exceeds a threshold (e.g. 2%), pause new enrollments using it until reviewed. Protects sender reputation.
10. **Calendar booking integration** — when outcome=`interested` with `asked_for_meeting: true`, surface a Calendly/Cal.com link in the talent's UI for the follow-up reply. v0.2.
