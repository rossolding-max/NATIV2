# NATIV2 — AI Influencer Marketing Assistant

## Goal

Build an AI-powered assistant that helps an influencer (or a roster of influencers) **find, connect with, and close deals with brands** to promote their products. The assistant should automate the manual grind of brand discovery, outreach, negotiation, and deal admin — while keeping the creator in control of voice, values, and final approvals.

## Phases

| # | Phase | Status | Purpose |
|---|-------|--------|---------|
| 0 | **Agency Setup** | v0.1 spec + schema shipped | One-time agency identity + sender mailbox + DNS + 2-4 week warmup setup. Prerequisite to talent onboarding. v0.1 = single agent / single agency; v2 = multi-agent. |
| 1 | **Talent Profile** | v0.1 spec + data shipped | Capture everything the system needs about the creator(s) — identity, audience, history, rates, similar talents. The foundation every later phase reads from. |
| 1.5 | **Brand Deals (historical campaigns)** | v0.1 spec + schema shipped | Rich per-talent record of every past campaign — campaign type, deliverables, structured KPIs (reach / engagement / conversions / sales) with source provenance, outcome, re-engagement metadata. Powers citation material in outreach pitches and re-engagement timing in Brand Discovery. |
| 2 | **Brand Discovery & Targeting** | v0.1 spec + data shipped | For a given talent, produce a ranked list of industries to pitch and a ranked long-list of specific brands within them — with qualification filtering, sensitive-vertical warnings, and re-engagement on a monthly cron. |
| 3a | **Contact CRM** | v0.1 spec + schema shipped | For every primary-tier brand candidate, find the right named contacts (Apollo + LinkedIn API + web search) with verified emails, LinkedIn URLs, location, tenure, and a `decision_role` classification (CMO of a $50B brand is *not* the buyer for a £5k Reel — the IM Manager 2 levels down is). |
| 3b | **Outreach** | v0.1 spec + schemas + angles library shipped | AI-generated personalised email sequences per contact + decision_role, sent via Smartlead from per-talent domains, with reply detection, kill-on-reply, and full per-email analytics provenance. |
| 4 | **Deal Lifecycle** | v0.1 spec + schema shipped | Moves a deal through 5 stages — LEAD → PROPOSAL → CONTRACT → DELIVERY → CLOSE — from a Phase 3b `interested` reply through to a paid + archived deal. Auto-archives won deals into Phase 1.5 brand_deals. Structured loss-reason enum + funnel analytics. v0.1 tracks contracts/invoices manually; v2 adds DocuSign + Stripe + Xero API integrations. |
| 4.5 | **Discovery Call Prep** | v0.1 spec + schema shipped | Auto-drafts agenda + briefing notes + slide deck (live + leave-behind variants + speaker notes) when a LEAD-stage deal hits `initial_call_scheduled`. 3-pass Claude Sonnet pipeline + Exa external research. Pre-generation guidance + natural-language feedback loop creates versioned regenerations. Slide skill (provided separately) handles HTML/PDF/PPT export with direct user editing + NL feedback per slide. Agency branding from Phase 0. |
| 4.6 | **Proposal Pack** | v0.1 spec + schema shipped | Agent-initiated commercial proposal builder for PROPOSAL substage. Forks discovery deck content + adds proposal-specific sections (executive summary, objectives recap, deliverables, fee, usage rights, exclusivity, timeline, exclusions). 5-stage pipeline: context augmentation (upload briefs/notes/transcripts → parse + summarise) → hybrid discovery debrief extraction → commercial gate (LLM proposes, agent must confirm before render) → 3-pass Sonnet slide generation → render. Bidirectional link to `deal.proposal.negotiation_log[]` for brand pushback handling. v0.1 file parsing: pypdf + python-docx. v2 adds external transcript-link references (Otter / Fireflies / Grain). |
| 4.7 | **Contract Pack** | v0.1 spec + schema shipped | Agent-initiated contract draft builder for CONTRACT substage. 7-stage pipeline: context augmentation (upload brand legal info, brand-requested clauses, prior contracts) → merge field extraction (talent legal entity from `billing_entity`, commercials from `deal.proposal.*`) → conditional clause evaluation (LLM decides include/exclude per `{{#if}}` block: GDPR, exclusivity, IP, paid social) → narrative drafting (LLM fills `{{narrative_*}}` placeholders) → compose → HARD LEGAL REVIEW GATE → render (markdown source-of-truth + Word .docx + PDF). Per-talent template (captured in Phase 1 onboarding Step 7.5) with markdown + merge fields + conditional sections + narrative placeholders. Brand-redline-response regen type. v0.1 e-sign = manual; v2 = DocuSign / PandaDoc / HelloSign. |
| 4.8 | **Invoice Pipeline** | v0.1 spec + schema shipped | Three-layer system. (1) Detection: cron polls Meta Graph + TikTok Display APIs (v0.1; v2 = Phyllo for YouTube/LinkedIn/X/podcast/Substack) every 15min-1hr, scores candidate posts against `posting_schedule[]` via time/handle/hashtag/format signals, surfaces matches to agent for confirmation. (2) Generation: LLM auto-parses contract's `payment_terms` into `invoice_schedule[]` (one-time agent gate); each schedule entry fires its own invoice_pack at its trigger_condition (contract_executed / first_post_live / all_deliverables_live / specific_date / manual); deterministic merge field extraction + optional LLM narrative line items + compose + render PDF. Agent reviews + sends (soft gate; sending IS the approval). (3) Tracking: per-invoice payment_state with status enum (draft/sent/viewed/paid/overdue/disputed/void); daily overdue cron with reminder log; v0.1 manual `payment_received_at`; v2 Stripe/Xero/QuickBooks webhook auto-populates. Multi-invoice from v0.1. Agency-wide template captured in Phase 0 Step 5.5. All invoices paid + final KPIs + final report → auto-archive to Phase 1.5. |

## End-to-end data flow

```
┌────────────────────────────────────────────────────────────────────┐
│ Phase 0  AGENCY SETUP (one-time, prerequisite to Phase 1)          │
│   docs/agency_setup_workflow.md                                    │
│   schemas/agency_profile.schema.json                               │
│     9-step setup: agency identity → visual branding → primary    │
│     agent → DNS → mailbox → signature → invoice template →        │
│     agent → DNS records →                                          │
│     sending mailbox provisioning → signature template → 2-4 week  │
│     warmup → validation                                            │
│     output: data/agency_profile.json (gitignored)                  │
│   v0.1: single agent / single agency. v2: multi-agent within agency│
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 1  TALENT PROFILE                                            │
│   docs/onboarding_workflow.md     ← how a talent gets in           │
│   schemas/talent.schema.json      ← what the data looks like       │
│   talents/{id}.json               ← per-talent file                 │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 1.5  BRAND DEALS (historical campaigns)                      │
│   docs/brand_deals_workflow.md                                     │
│   schemas/brand_deal.schema.json                                   │
│     ingestion: media pack (AI extracts KPIs) + manual form +       │
│                platform-API auto-pull (IG/TikTok/YouTube insights) │
│     per deal: campaign type + deliverables + KPIs with source      │
│                provenance + outcome + re-engagement metadata       │
│     output: data/brand_deals/{talent_id}.json (gitignored)         │
│   feeds: Phase 2 Search 1 (re-engagement), Phase 3b AI generation  │
│           (citation material), Phase 3a warm-intro identification  │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 2A  INDUSTRY RECOMMENDATION                                  │
│   docs/recommendation_algorithm.md                                 │
│     5-layer score: direct(60%)+bridge(25%)+past(5%)+pref(10%)+pol  │
│     reads: niches.json, industries.json, *_affinity.json, IAB taxo │
│     output: ranked industry list with `why[]`                      │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 2B  BRAND DISCOVERY (16 parallel searches)                   │
│   docs/brand_discovery.md                                          │
│     reads: talent profile + every data/*.json + Exa + last30days   │
│     output: data/brand_candidates/current/{talent_id}.json         │
│     schema: schemas/brand_candidates.schema.json                   │
│   monthly cron + on-profile-change + on-demand                     │
└────────────────────────────┬───────────────────────────────────────┘
                             │
        (background, continuous)
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 2C  BRAND ENRICHMENT (writeback loop)                        │
│   docs/brand_enrichment_workflow.md                                │
│     9-step pipeline: identity → domain → industry → HQ/markets →   │
│     stage → tier → creator program → financials → social followers │
│     output: data/brand_industry_map.json grows over time           │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 3a  CONTACT CRM                                              │
│   docs/contact_enrichment_workflow.md                              │
│     9-step pipeline: identify target roles → Apollo lookup →       │
│     LinkedIn API enrichment → web-search backup → email verify →   │
│     decision-role classify → placeholders → dedup → write          │
│     output: data/brand_contacts/{brand_id}.json (gitignored, PII)  │
│     schema: schemas/brand_contact.schema.json                      │
│   triggered on primary-tier brand promotion + manual + quarterly   │
└────────────────────────────┬───────────────────────────────────────┘
                             │
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 3b  OUTREACH                                                  │
│   docs/outreach_workflow.md                                         │
│     Per qualified contact + decision_role: select template →        │
│     evaluate angles (data/pitch_angles.json) → AI-generate every    │
│     step (Claude Sonnet step 1, Haiku follow-ups) → review queue →  │
│     push to Smartlead → real-time webhooks → reply classification   │
│     → kill across roster → analytics aggregation                    │
│   schemas/pitch_template + pitch_enrollment + pitch_angle           │
│   send via Smartlead from the agency's mailbox                      │
└────────────────────────────┬───────────────────────────────────────┘
                             │ reply outcome=interested
                             ▼
┌────────────────────────────────────────────────────────────────────┐
│ Phase 4  DEAL LIFECYCLE                                             │
│   docs/deal_lifecycle_workflow.md                                   │
│     5 stages: LEAD → PROPOSAL → CONTRACT → DELIVERY → CLOSE         │
│     Each with substages, per-stage data blocks, state machine.      │
│     v0.1 = manual contracts/invoices (PDF + dates);                 │
│     v2 = DocuSign + Stripe + Xero API.                              │
│     Structured loss-reason enum at any stage → funnel analytics.    │
│   schemas/deal.schema.json                                          │
│   output: data/deals/{deal_id}.json (gitignored)                    │
└────────────────────────────┬───────────────────────────────────────┘
              │                                  │
   substage = initial_call_scheduled             │ on close + payment + KPIs:
              ▼                                  │ auto-archive
┌────────────────────────────────────────────┐   │
│ Phase 4.5  DISCOVERY CALL PREP             │   │
│   docs/discovery_prep_workflow.md          │   │
│     3-pass Sonnet: briefing → agenda →     │   │
│     slides[]; + Exa external research.     │   │
│     Outputs: live deck + leave-behind      │   │
│     deck + speaker notes (PDF/HTML/PPT).   │   │
│     Pre-generation guidance + NL feedback  │   │
│     loop → versioned regenerations.        │   │
│     Slide skill (user-provided) handles    │   │
│     direct edit + per-slide NL feedback.   │   │
│     Agency branding from Phase 0.          │   │
│   schemas/discovery_prep_pack.schema.json  │   │
│   output: data/deals/{deal_id}/prep_packs/ │   │
│   v{N}.json (gitignored)                   │   │
└──────────┬─────────────────────────────────┘   │
           │ deal.substage → proposal_drafting   │
           ▼                                     │
┌────────────────────────────────────────────┐   │
│ Phase 4.6  PROPOSAL PACK                   │   │
│   docs/proposal_pack_workflow.md           │   │
│     5-stage pipeline:                      │   │
│     A. Context augmentation                │   │
│        (upload PDF/Word/text/notes)        │   │
│     B. Hybrid debrief extraction           │   │
│        (LLM → agent reviews → confirms)    │   │
│     C. Commercial gate                     │   │
│        (LLM proposes; agent MUST confirm   │   │
│         before slides render)              │   │
│     D. 3-pass Sonnet slide generation      │   │
│        (forks discovery slides + adds      │   │
│         exec summary / objectives recap /  │   │
│         deliverables / investment / etc.)  │   │
│     E. Render (HTML / PDF / PPTX)          │   │
│     Bidirectional link to deal.proposal    │   │
│     .negotiation_log[] for brand pushback. │   │
│   schemas/proposal_pack.schema.json        │   │
│   output: data/deals/{deal_id}/            │   │
│     proposal_packs/v{N}.json + uploads     │   │
│     (gitignored)                           │   │
└──────────┬─────────────────────────────────┘   │
           │ deal.substage → contract_drafting   │
           ▼                                     │
┌────────────────────────────────────────────┐   │
│ Phase 4.7  CONTRACT PACK                   │   │
│   docs/contract_pack_workflow.md           │   │
│     7-stage pipeline:                      │   │
│     A. Context augmentation                │   │
│        (upload brand legal info, prior     │   │
│         contracts, redlines)               │   │
│     B. Merge field extraction              │   │
│        (talent.billing_entity +            │   │
│         deal.proposal.* → merge values     │   │
│         with confidence + source)          │   │
│     C. Conditional clause evaluation       │   │
│        (LLM decides include/exclude per    │   │
│         {{#if}}: GDPR, exclusivity, IP)    │   │
│     D. Narrative drafting                  │   │
│        ({{narrative_*}} placeholders)      │   │
│     E. Compose markdown                    │   │
│     F. HARD LEGAL REVIEW GATE              │   │
│        (no render until approved)          │   │
│     G. Render (MD source-of-truth +        │   │
│        DOCX + PDF)                         │   │
│     Per-talent template captured in        │   │
│     Phase 1 onboarding Step 7.5.           │   │
│   schemas/contract_pack.schema.json        │   │
│   output: data/deals/{deal_id}/            │   │
│     contract_packs/v{N}.json (gitignored)  │   │
└──────────┬─────────────────────────────────┘   │
           │ contract_executed → schedule parse  │
           │ all_deliverables_live → invoice     │
           ▼                                     │
┌────────────────────────────────────────────┐   │
│ Phase 4.8  INVOICE PIPELINE                │   │
│   docs/invoice_workflow.md                 │   │
│     Layer 1 — DETECTION                    │   │
│       Cron polls Meta Graph (IG) + TikTok  │   │
│       Display APIs every 15min-1hr; scores │   │
│       candidates vs posting_schedule[];    │   │
│       agent confirms each match.           │   │
│       v2: Phyllo for YouTube/LinkedIn/X/   │   │
│       podcast/Substack.                    │   │
│     Layer 2 — GENERATION                   │   │
│       LLM parses contract.payment_terms →  │   │
│       invoice_schedule[] (1-time gate).    │   │
│       Each entry fires invoice_pack at     │   │
│       trigger_condition (contract_executed │   │
│       / all_deliverables_live / etc.).     │   │
│       Deterministic merge + optional LLM   │   │
│       narrative line items + PDF render.   │   │
│       Agent reviews + sends (soft gate).   │   │
│     Layer 3 — TRACKING                     │   │
│       Per-invoice payment_state. Daily     │   │
│       overdue cron. v0.1 manual; v2 Stripe │   │
│       /Xero/QuickBooks webhook.            │   │
│     All paid + final KPIs + final report   │   │
│     → auto-archive to Phase 1.5.           │   │
│   schemas/invoice_pack.schema.json         │   │
│   output: data/deals/{deal_id}/            │   │
│     invoice_packs/seq{N}_v{M}.json         │   │
│     (gitignored)                           │   │
└────────────────────────────────────────────┘   │
                                                 ▼
                                  ┌─────────────────────────┐
                                  │  Phase 1.5 brand_deals  │
                                  │  (closes the loop)      │
                                  └─────────────────────────┘

   Cross-cutting:  docs/vendor_roadmap.md  ← external services + env vars
```

---

## Phase 1 — Talent Profile

### Output
A JSON file (`talents/*.json`) per talent, validated against `schemas/talent.schema.json`. The repo supports a **multi-talent roster** — one file per creator, or a combined roster file.

### Captured fields
- **Identity**: id, name, pronouns, age/DOB, location, timezone, languages, bio, content niches.
- **Contact**: direct email, manager/agency contact, phone (optional).
- **Billing entity**: company/legal name, country of operation, tax/VAT ID, preferred payment methods. _(Needed before any deal can be invoiced.)_
- **Platforms & handles**: per-platform handle, URL, follower count, engagement rate, avg views/likes/comments, and a **reference** to that platform's API key (e.g. `env:INSTAGRAM_TOKEN`) — never the raw secret.
- **Audience demographics**: age bands (IAB-aligned 5-year bands: 18-20, 21-24, 25-29, ..., 75+), gender split, top countries/cities, top languages, interests. Per-platform overrides supported.
- **Previous brand deals** (rich): brand name, industry, campaign date, platform, deliverables, fee (optional), usage rights granted, performance notes, brand contact.
- **Similar talent**: thin pointer (id, name, handles, previous brand collaborations). The app enriches each record by AI research and back-derives `inferred_niches` from the brand list — see `docs/recommendation_algorithm.md` § Similar-talent inversion.
- **Rate card**: per platform → per deliverable type (e.g. Instagram → Reel / Story / Feed / Carousel / Live). Supports bundles, usage rights uplift %, exclusivity uplift %, whitelisting uplift %.
- **Brand preferences & restrictions**: preferred industries, blocked industries (e.g. gambling, alcohol), active exclusivities (with end date), values/red lines.
- **Working terms**: default usage rights (organic / whitelisting / paid social), default usage duration, content turnaround time, revisions included, blackout/availability dates.
- **Press kit & assets**: link to media kit, headshots, demo reels, notable press mentions, awards.
- **Disclosure defaults**: FTC/ASA disclosure style (`#ad`, `#sponsored`, etc.).
- **Other stats**: free-form key/value bag for anything that doesn't fit (e.g. newsletter subs, podcast downloads, Discord size).

### Added beyond the original brief
The fields below were not in the original request but were added because later phases (outreach, negotiation, contracts, invoicing) will fail without them:
- Billing entity / tax info.
- Per-platform follower count, engagement rate, avg views/likes/comments (live stats — needed for media-kit-style pitches).
- Brand preferences/restrictions and active exclusivities (so the assistant doesn't pitch a conflicting brand).
- Default usage rights, turnaround, revisions (so rate-card quotes are apples-to-apples).
- Disclosure defaults (compliance).
- Press kit URL and assets (so outreach emails can attach proof).
- Free-form `other_stats` bag for anything bespoke.

### Files
- `schemas/agency_profile.schema.json` — JSON Schema for the Phase 0 agency identity. Captures agency name/domain, the primary agent's identity, sending mailbox + warmup state, default signature template, CAN-SPAM-required company address. v0.1 enforces single-agent constraint via `agents` `maxItems: 1`. Validates `data/agency_profile.json` (gitignored).
- `schemas/deal.schema.json` — JSON Schema for Phase 4 deal pipeline records. 5-stage lifecycle (LEAD → PROPOSAL → CONTRACT → DELIVERY → CLOSE) + substages + state machine + per-stage data blocks + attachments + notes + audit trail. Structured loss-reason enum. `lead.discovery_prep_pack_ids[]` + `lead.latest_prep_pack_id` link to Phase 4.5 prep packs. v0.1 = manual contracts/invoices; v2 fields ready for DocuSign / Stripe / Xero / QuickBooks API integration. Validates files under `data/deals/` (gitignored — commercial data + contracts + invoice amounts).
- `schemas/discovery_prep_pack.schema.json` — JSON Schema for Phase 4.5 discovery-call prep packs. Versioned (v1, v2, v3…) bundles of briefing notes (multi-section markdown, agent-only, includes commercial range), agenda (sections + durations + talking points), and slides[] (structured JSON: live_body + leave_behind_extension + speaker_notes + sources per slide). Generation block captures pre-generation guidance + regeneration feedback + LLM provenance (model + token usage + cached tokens + cost). Context snapshot freezes upstream data including Exa external research (queries + summaries + URLs). agent_edits[] audit log for direct edits. export_artifacts[] tracks rendered HTML/PDF/PPT files. Validates files under `data/deals/{deal_id}/prep_packs/` (gitignored).
- `schemas/proposal_pack.schema.json` — JSON Schema for Phase 4.6 proposal packs. Versioned commercial proposals with five layered sections: (1) generation provenance (5 trigger types including `negotiation_response` with bidirectional log ref); (2) context snapshot (forked_from_prep_pack_id + discovery_debrief_snapshot + optional Exa research refresh); (3) context_artefacts[] (uploaded files with parser metadata, parsed text, LLM summary, extracted signals, relevance tags, exclude toggle); (4) commercial_proposal (LLM-proposed deliverables/fee/usage_rights/exclusivity/timeline/exclusions/payment_terms with rationale per field, plus the gate: confirmed_at + confirmed_by_agent_id + confirmed_overrides[]); (5) slides[] (16-value type enum including forked types from discovery + proposal-specific: executive_summary, objectives_recap, recommendation, deliverables, timeline, investment, usage_rights, exclusivity, exclusions, agency_process, next_steps_proposal; live_body adds `table` for deliverables/timeline/investment). export_artifacts[].status enum includes `blocked_by_commercial_gate`. agent_edits[] includes `commercial_override` and `context_artefact_*` types. Validates files under `data/deals/{deal_id}/proposal_packs/` (gitignored).
- `schemas/contract_pack.schema.json` — JSON Schema for Phase 4.7 contract packs. Versioned contract drafts with eight layered sections: (1) generation provenance (6 trigger types including `brand_redline_response` and `amendment_request`); (2) context snapshot (template_version_used + proposal_pack_id_at_gen + talent_billing_entity_snapshot + brand_legal_entity_at_gen with signatory info); (3) context_artefacts[] with contract-specific types (brand_legal_info / brand_requested_clauses / prior_contract / brand_redline / talent_redline); (4) merge_field_values[] (each with confidence enum high/medium/low/missing + source enum + needs_review flag); (5) conditional_clause_decisions[] (each with decided_by + applicability_rationale + agent_overridden); (6) narrative_sections[] (LLM-drafted with sources[] + word_count); (7) composed_markdown (canonical contract source-of-truth); (8) legal_review (the gate — required flag, reviewer_id, blocking_issues[] auto-populated, approved_at + approved_by_agent_id, previous_approvals[] audit of edit-reset-reapprove cycles). export_artifacts[].status enum includes `blocked_by_legal_gate`. agent_edits[] includes 7 edit types and the `trivial_edit_override` flag for typos. Validates files under `data/deals/{deal_id}/contract_packs/` (gitignored).
- `schemas/invoice_pack.schema.json` — JSON Schema for Phase 4.8 invoice packs. Versioned per-schedule-sequence invoices (`inv_..._seq{N}_v{M}` IDs). Eight sections: (1) generation provenance (5 trigger types: schedule_trigger_fired / agent_initiated / agent_regenerate / brand_revision_request / amendment_invoice; captures which trigger_condition fired); (2) context snapshot (contract_pack_id_at_gen + talent_billing_entity_snapshot + brand_legal_entity_snapshot + invoice_schedule_entry_snapshot + matched_posts[] with detection methods); (3) merge_field_values[] (same shape as contract_pack with invoice-specific source enum); (4) line_items[] (deliverable_ref + description + quantity + unit_price + amount + narrative_drafted_by_llm flag); (5) amounts (subtotal + tax_rate + tax_amount + tax_label + total + currency + fx_rate_to_usd); (6) composed_markdown (canonical invoice source-of-truth); (7) agent_review (soft gate — viewed_at + sent_at + send_method enum supporting v2 stripe_invoice_send / xero_send / quickbooks_send + sent_to_email); (8) payment_state (status 7-value enum + due_at + payment_received_at + method enum + amount + reference + external_invoice_id + reconciliation_note). payment_reminder_log[] for overdue cron audit. agent_edits[] for draft mutability + post-send immutability. Validates files under `data/deals/{deal_id}/invoice_packs/` (gitignored).
- `schemas/talent.schema.json` — JSON Schema (Draft 2020-12) describing the talent profile.
- `schemas/brand_candidates.schema.json` — JSON Schema for the per-talent Brand Discovery output. Validates every file written by the orchestrator under `data/brand_candidates/` (the folder itself is gitignored — generated artifact, not source).
- `schemas/brand_contact.schema.json` — JSON Schema for per-brand contact records (Phase 3a). Validates every file under `data/brand_contacts/` (gitignored — contacts are PII and vendor data is licensed).
- `schemas/brand_deal.schema.json` — JSON Schema for per-talent historical brand-deal records (Phase 1.5). 13 structured sections per deal incl. KPIs with source provenance, vs-benchmark, audience-overlap, re-engagement metadata. Validates every file under `data/brand_deals/` (gitignored — commercial KPIs and fees).
- `schemas/pitch_angle.schema.json` + `data/pitch_angles.json` — curated library of 42 pitch angles across 15 categories (37 base + 5 KPI-driven angles from Phase 1.5) (competitive proof, similar-talent precedent, demographic match, niche fit, brand momentum, geographic alignment, mutual connection, values alignment, re-engagement, performance proof, timeliness, creative concept, insider observation, role defaults, counter-positioning). Each angle has trigger conditions, applicable decision roles + steps, strength score, example phrasing. Powers the AI generation step in Phase 3b outreach.
- `schemas/pitch_template.schema.json` — sequence templates (structure not content). Per-step intent + timing + preferred angle categories. 3 default templates ship per decision_role.
- `schemas/pitch_enrollment.schema.json` — running instance of a template for a specific (talent, contact). Full per-email provenance: which angles used, which model, full engagement event log, LLM-classified outcome. Validates files under `data/pitch_enrollments/` (gitignored).
- `scripts/analyze_outreach.py` — rolls every enrollment step into A/B-sliceable aggregates (by angle, decision_role, template, step, brand_tier, send_time, subject_pattern, sender_domain, etc.). Outputs `data/outreach_analytics/` (gitignored).
- `talents/example-talent.json` — template instance, partially filled.
- `data/niches.json` — canonical creator content-niche taxonomy (145 entries).
- `data/industries.json` — canonical brand-industry taxonomy (178 entries).
- `data/brand_industry_map.json` — seed lookup of well-known brand names → `industry_id` (290 brands, all enriched with `hq_country`, `sells_in_countries`, `company_stage`, `typical_campaign_tier`, `creator_program_presence` for Brand Discovery searches; **62% additionally carry `revenue`, 70% `headcount` bands, 62% `social_followers` per platform** with `source` provenance and `as_of_year` — honest-gaps policy: omitted when not confident). Used by the app's auto-complete and grows over time.
- `data/brand_competitors.json` — curated brand-to-brand direct-competitor graph (290 brands, 1,241 directed edges). Powers Brand Discovery Search 3/4/14 (direct + transitive competitor lookups). Captures actual competitive sets (Tesla ↔ Rivian/Polestar/Lucid) rather than just same-industry membership.
- `data/iab_audience_taxonomy_v1.1.json` — official IAB Tech Lab Audience Taxonomy v1.1 (1,558 segments), used as the audience-profile bridge between niches and industries.
- `data/niche_industry_affinity.json` — direct authored niche↔industry affinity matrix (1,246 edges across 145 niches).
- `data/niche_audience_affinity.json` — bridge leg 1: niche → IAB audience segments.
- `data/industry_audience_affinity.json` — bridge leg 2: industry → IAB audience segments.
- `scripts/build_affinity.py` — builder script with all authored data and inline validation. Single source of truth for the three affinity files; re-run to regenerate them.
- `scripts/enrich_brand_map.py` — adds the 5 metadata fields per brand to `brand_industry_map.json`. Re-runnable; honest-gaps policy (omit fields where the curated value is unknown).
- `docs/recommendation_algorithm.md` — draft spec for how the app combines all of the above into a ranked list of industries to target for a given talent. Forward-looking contract for when the app is built.
- `docs/agency_setup_workflow.md` — Phase 0 one-time setup before any talent onboards. 9-step process: agency identity, visual branding (logo + colors + fonts — feeds every downstream agency artefact), primary agent, DNS records (SPF/DKIM/DMARC), sending mailbox provisioning via Smartlead, signature template (CAN-SPAM-compliant), invoice template (numbering format + tax handling + payment instructions — feeds Phase 4.8 invoice generator), 2-4 week warmup, final validation. v0.1 single-agent constraint documented; v2 expansion plan for multi-agent rosters.
- `docs/deal_lifecycle_workflow.md` — Phase 4 spec for the deal pipeline. Defines the 5-stage lifecycle (LEAD → PROPOSAL → CONTRACT → DELIVERY → CLOSE), per-stage substages and data blocks, full state machine with valid transitions, structured loss reasons (budget / timing / competitor_won / internal_pivot / talent_no_fit / terms_disagreed / unresponsive / compliance_block / other), auto-archive on close into Phase 1.5 brand_deals, integration touchpoints with Phase 3b outreach (interested reply triggers deal creation) and Phase 1.5 (close triggers archive), notifications + reminders driven by `next_action_due_at`, failure handling, and the v2 vendor-integration roadmap (DocuSign / PandaDoc / HelloSign for e-sign; Stripe / Xero / QuickBooks for invoicing).
- `docs/discovery_prep_workflow.md` — Phase 4.5 spec for the discovery-call prep generator. Defines the trigger (`substage = initial_call_scheduled`), 3-pass Sonnet generation pipeline with prompt-caching across briefing/agenda/slides passes, Exa external research integration, default 10-slide deck structure mapped to slide-type layouts, three rendered output variants from one source (live deck + leave-behind deck + speaker notes), versioning model with pre-generation guidance + natural-language feedback regeneration loop (v1 stays locked unless agent asks; agent can target whole-pack / section / per-slide regen), direct slide editing via the slide skill, slide-skill integration contract (input/output shape + on_edit/on_feedback callbacks), failure handling, storage layout, v0.1 explicit non-goals, and 7 open questions for v0.2.
- `docs/proposal_pack_workflow.md` — Phase 4.6 spec for the commercial proposal pack generator. Defines the agent-initiated trigger (substage = `proposal_drafting`), 5-stage generation pipeline (context augmentation → hybrid debrief extraction → commercial gate → 3-pass Sonnet slide generation → render), file upload + parsing (pypdf / python-docx / text reader for v0.1; external transcript-link references for v2), the commercial gate mechanics (LLM proposes, agent must confirm before slides render, confirmed values copy into canonical `deal.proposal.*`), default 15-slide deck structure with 4 slides forked from the discovery prep pack, negotiation tie-in (bidirectional link to `deal.proposal.negotiation_log[].proposal_pack_version`), storage layout, integration touchpoints, 9 failure handling scenarios, and 7 open questions for v0.2 including counter-offer detection, win/loss pricing-model calibration, auto-contract-draft seeding.
- `docs/contract_pack_workflow.md` — Phase 4.7 spec for the contract pack generator. Defines the agent-initiated trigger (substage = `contract_drafting`), 7-stage generation pipeline (context augmentation → merge field extraction → conditional clause evaluation → narrative drafting → compose → HARD legal review gate → render), per-talent template structure (markdown + merge fields + `{{#if}}` conditionals + `{{narrative_*}}` placeholders) captured in Phase 1 onboarding Step 7.5, full example template markdown demonstrating ~20 merge fields + 4 conditional blocks + 4 narrative placeholders, the legal review gate mechanics (blocking_issues auto-populated from low-confidence fields; edits reset gate; trivial_edit_override for typos; previous_approvals[] audit trail), brand-redline-response handling, storage layout, integration touchpoints with `talent.contract_template` + `talent.billing_entity` + Phase 4.6 proposal pack, 10 failure handling scenarios, and 7 open questions for v0.2 including brand-side legal review automation, counter-template handling, structured JSONLogic clause conditions.
- `docs/invoice_workflow.md` — Phase 4.8 spec for the invoice pipeline. Three layers: (1) deliverable detection via Meta Graph + TikTok Display APIs in v0.1 (Phyllo for YouTube/LinkedIn/X/podcast/Substack in v2), cron cadence (15min stories / 1hr other), candidate scoring algorithm with time_window + brand_handle + campaign_hashtag + content_type signals, confidence routing (≥80/50-79/<50), agent confirmation flow, per-platform API endpoints + rate limits + oAuth scope notes; (2) invoice generation including LLM parse of contract `payment_terms` into structured `invoice_schedule[]` with one-time agent gate, per-trigger invoice pack pipeline (Stages A-E), invoice numbering atomic increment, multi-invoice from v0.1 with `seq{N}_v{M}` naming; (3) payment tracking with status enum + daily overdue cron + reminder log + auto-archive interaction. Storage layout, integration touchpoints across Phases 0/1/4.6/4.7, consolidated 9 failure handling scenarios, cost profile, 7 v0.1 non-goals, 8 v0.2 open questions including detection signal tuning + auto-reminder + per-jurisdiction tax + Stripe Connect for marketplace flows.
- `docs/onboarding_workflow.md` — draft spec for how a user adds a new talent: web wizard with OAuth platform connections (paste-fallback), media-pack extraction by LLM, adaptive questionnaire for gaps, hybrid similar-talent seeding (user + AI suggestions), and a background AI research pass that populates similar-talent records. The per-talent sender-domain section was removed: outreach now uses the agency's pre-warmed mailbox from Phase 0.
- `docs/brand_discovery.md` — draft spec for the long-list generator. **16 independent searches** runnable today (re-engagement, network expansion, affinity expansion, geo, life-stage, constraint-aware, graph, recently-funded via web search, **trending/rising brands via the [`last30days` skill](https://github.com/mvanhorn/last30days-skill) — multi-source social momentum signal across Reddit/X/TikTok/YouTube/HN/etc., run as a monthly cron**) merged with multi-source scoring. Monthly cron drives re-engagement with per-brand cool-downs. Future-versions section lists 12 more searches that need external data (Crunchbase API as a structured upgrade to Search 15, live `#ad` scraping, affiliate networks, creator marketplaces, EMV reports, etc.). Both structural enrichments (`brand_industry_map` metadata + `brand_competitors` graph) are now shipped and used by Searches 3, 4, 10, 14.
- `docs/vendor_roadmap.md` — single source of truth for external-service decisions. Confirms **Exa** as the v0.1 web-search provider (Search 15). Catalogues deferred vendors with criteria for when to add each: ScrapeCreators (Search 16 visual platforms), Owler (competitor maintenance), Modash/HypeAuditor (brand DB bulk import), Exploding Topics (pre-trend detection), Product Hunt API (day-of launches), Tribe Dynamics EMV (top-spending brands per category), SimilarWeb (audience-overlap competitors), Crunchbase (structured funding data), Apollo (Phase 3 outreach contact discovery), plus alternatives for each. Includes the env-var inventory for all current + deferred services.
- `docs/brand_enrichment_workflow.md` — draft spec for the 9-step pipeline that takes a brand from name-only to fully-populated record in `brand_industry_map.json`. Covers identity resolution, domain resolution, industry classification, HQ/markets, company stage, campaign tier, creator-program presence, revenue + headcount, social follower counts. Three triggers (seed expansion / in-flight discovery writeback / annual refresh), tool-per-step mapping, honesty-floor policy, validation gates, and a state machine. Pairs with brand_discovery.md (consumer) and vendor_roadmap.md (external services).
- `docs/contact_enrichment_workflow.md` — Phase 3a spec for the 9-step pipeline that turns a primary-tier brand candidate into a list of named contacts with verified emails, LinkedIn URLs, location, tenure, and decision-role classification. Covers target-role identification (scaled to brand size), Apollo employee lookup, LinkedIn API enrichment, web-search backup via Exa, email verification, LLM-driven decision-role classification with the simplified 5-value taxonomy (`buyer` / `influencer` / `gatekeeper` / `champion` / `unknown`), placeholder generation for known-but-unfilled roles, cross-source dedup, CAN-SPAM-aligned opt-out handling, and the shared-roster-pool / per-talent-pitch-history model.
- `docs/brand_deals_workflow.md` — Phase 1.5 spec for the rich brand-deal data layer: schema, three ingestion paths (media pack AI extraction / manual form / platform-API auto-pull), KPI computation rules (CPM/CPE/CTR auto-derived), honesty-floor enforcement, deal lifecycle states (drafted → live → completed → kpis_in → renewal_eligible), integration touchpoints with Brand Discovery Search 1 (re-engagement timing), Outreach AI generation (citation material), and Contact Enrichment (warm-intro identification via `main_brand_contact_id` following the contact between brands).
- `docs/outreach_workflow.md` — Phase 3b spec for the AI-generated cold-outreach engine. Covers template selection per decision_role, angle evaluation against the 37-angle library, per-step AI generation (Claude Sonnet for first touch / Haiku for follow-ups), review-before-send queue, Smartlead campaign push, real-time webhook handling, reply classification + cross-roster kill logic, per-talent sender domain setup (SPF/DKIM/DMARC + 2-4 week warmup), and the analytics aggregation layer that captures every email's full provenance for A/B analysis. Includes the default templates (buyer-direct-pitch 4 steps, influencer-warm-intro 3 steps, champion-activation 2 steps; gatekeeper = manual only).
- `.gitignore` — ensures any `*.local.json` or `.env` files containing real keys are never committed.

### Reference taxonomies
Both taxonomy files follow the same shape:
```jsonc
{
  "version": "1.0.0",
  "items": [
    { "id": "kebab-case-slug", "name": "Display Name", "parent": "parent-id-or-null", "aliases": ["search", "terms"] }
  ]
}
```
Top-level entries have `parent: null`; sub-entries reference their parent's `id`. `industries.json` additionally flags `sensitive: true` for categories that are commonly restricted on social platforms or require explicit creator opt-in (alcohol, gambling, tobacco, crypto, etc.).

### How the talent profile links to the taxonomies
The talent profile stores **only `id` slugs**, never display names — that way display labels, translations, and re-namings can change in the taxonomy files without touching any talent record.

| Profile field | References | Validated by |
|---|---|---|
| `content_niches[]` | `data/niches.json` `id` | Schema pattern (`#/$defs/nicheId`) + app load-time check against taxonomy |
| `previous_brands[].industry_id` | `data/industries.json` `id` | Schema pattern (`#/$defs/industryId`) + app load-time check |
| `brand_preferences.preferred_industries[]` | `data/industries.json` `id` | Same |
| `brand_preferences.blocked_industries[]` | `data/industries.json` `id` | Same |
| `brand_preferences.active_exclusivities[].industry_id` | `data/industries.json` `id` | Same |
| `similar_talent[].previous_brands[].industry_id` | `data/industries.json` `id` | Same |

JSON Schema validates the **slug format** (kebab-case). The app validates **slug membership** in the taxonomy on load, since JSON Schema can't dereference external JSON for `enum`.

### Auto-completing `industry_id` from a brand name
When the user types a brand into `previous_brands[].brand`, the app resolves `industry_id` automatically. Resolution order:

1. **Exact match** on `name` in `data/brand_industry_map.json` (case-insensitive).
2. **Alias match** on the `aliases[]` of each entry.
3. **Domain match** if the user pasted a URL or `@domain`.
4. **AI inference fallback** (later phase) — the assistant reads the brand's website / first-page search results and classifies it against `data/industries.json`. The result is then **written back** to `data/brand_industry_map.json` so future lookups are instant and the seed grows.

If multiple matches tie (rare), the app prefers the entry with the more specific (child) `industry_id` over a parent sector.

Each brand record also carries enrichment fields (`hq_country`, `sells_in_countries`, `company_stage`, `typical_campaign_tier`, `creator_program_presence`) used by Brand Discovery searches. Fields are present only when there's a confident value — absence means "not yet enriched"; the app treats missing as unknown rather than assuming a default.

### Niche ↔ Industry affinity (which industries resonate with which niches)
Two complementary models, both kept in sync by `scripts/build_affinity.py`.

**1. Direct model (`niche_industry_affinity.json`)**
Hand-authored edge list. Each niche has up to three tiers of matched industries (`primary` / `secondary` / `tertiary`) and a group-level `evidence` field citing the source of the mapping. Per-edge `overrides[]` can carry edge-specific evidence (case studies, sensitive-vertical flags).

- Edges are **symmetric**: one strength per pair.
- Edges are **quality-floored**: present only if there is either a citable source or a non-generic logical reason. Broad-audience niches (`comedy`, `lifestyle`, `entertainment`) ship with fewer edges by design, not more.
- Sub-niches **inherit** their parent's edges via app-side fallback unless they have their own entry.

Evidence sources used: `iab`, `imh` (Influencer Marketing Hub), `hypeauditor`, `case-study`, `logic`.

**2. Bridged model (via IAB Audience Taxonomy v1.1)**
Uses the official IAB taxonomy as a shared vocabulary between creators and advertisers — the same crosswalk that ad platforms (Meta, Google, TikTok Ads) build internally.

Both sides cite from all three IAB vocabularies for a real, bidirectional bridge:

- `niche_audience_affinity.json` — every niche links to relevant IAB **Interest** (what its audience consumes), **Purchase Intent** (what its audience buys), and **Demographic** (who they are) segments.
- `industry_audience_affinity.json` — every industry links to relevant IAB **Interest** (what content its target customer engages with), **Purchase Intent** (what its target customer is in-market to buy), and **Demographic** segments.
- Niche↔industry affinity is then **computed at runtime** as the overlap of their IAB segment vectors across all three vocabularies.

Talent audience demographics are **IAB-aligned by schema** (the 13 IAB Age Range bands are the only allowed `age_bands` keys), so a specific talent's `audience_demographics` plugs into the bridge directly. The system can therefore compute "best industries for *this* talent" — not just the niche baseline — and explain matches in IAB terms ("matched because both target IAB segment [1377] Family and Parenting and Demo [25-29, 30-34, Female]").

**Why two models?** Direct is fast and trustworthy for ranking. Bridged adds compositional explainability and lets the recommender combine niche signal with the specific talent's real demos. The two are combined in `docs/recommendation_algorithm.md`.

### Recommendation algorithm
The full recipe — how the app combines direct affinity + IAB bridge + past deals + brand preferences + the sensitive flag into a ranked list of industries with `why[]` explanations and `warnings[]` — lives in `docs/recommendation_algorithm.md`. That document is the contract the app will implement.

---

## Phase 1.5 — Brand Deals (historical campaigns)

### Output
A rich, per-talent record of every brand campaign — past, active, or upcoming. Lives at `data/brand_deals/{talent_id}.json` (gitignored — commercial KPIs and exact fees shouldn't be in repo). Validated against `schemas/brand_deal.schema.json`. The light `talent.previous_brands[]` array stays as a backwards-compatible index; each entry can carry an optional `deal_id` pointing to the rich record.

### What's captured per deal
13 structured sections per record:
- **Identity** — `deal_id`, `brand_id`, `industry_id`, `campaign_name`
- **Categorization** — `campaign_type` (13-value enum: sponsored_post / sponsored_series / ambassador / product_seeding / affiliate / ugc_license / whitelisting / paid_appearance / brand_integration / co_branded_product / podcast_read / newsletter_mention / other), `campaign_objective`
- **Timing** — `started_at`, `ended_at`, specific `posted_dates[]`
- **Deliverables** — `[{platform, format, count, post_urls[]}]`
- **Commercials** — `fee_usd`, original currency + amount, `usage_rights_granted[]`, `exclusivity{category, duration_days}`, additional non-cash compensation
- **KPIs** — structured per-metric records with source provenance: `reach`, `impressions`, `engagement_total`, `engagement_rate_pct`, `video_views`, `video_completion_rate_pct`, `saves`, `shares`, `comments`, `link_clicks`, `ctr_pct`, `conversions`, `sales_attributed_usd`, `cpm_usd`, `cpe_usd`, `emv_usd`, etc. Each value tagged `platform_verified` / `brand_reported` / `third_party` / `calculated` / `self_reported` / `estimated`.
- **vs_industry_benchmark** — schema in place; populated only when v2 ships `data/industry_kpi_benchmarks.json`
- **Audience match** — `audience_overlap_with_brand_target_pct` + snapshot of `audience_demographics_at_campaign_time`
- **Qualitative** — `performance_notes`, `outcome` (6 values incl. `successful_renewed`), optional `case_study_url`
- **Re-engagement metadata** — `do_not_recontact`, `cool_down_override_days`, `last_re_engagement_pitch_date`, `renewal_eligibility_date`
- **Contacts** — `main_brand_contact_id` (FK to brand_contacts) + optional `agency_contact_id`
- **Provenance** — `data_sources[]`, `first_recorded_at`, `last_updated_at`, `manually_verified_by_talent`
- **Linked enrollment** — `originated_from_pitch_enrollment_id` closes the loop: did this deal come from our outreach system?

### Three ingestion paths
- **Media pack extraction** (onboarding Step 3) — multimodal LLM extracts deals + KPIs from PDFs / PPTX / IG Insights screenshots / brand invoices. Marked `manually_verified_by_talent: false` pending Step 4 reconciliation.
- **Manual form** (onboarding Step 5 + ongoing) — guided per-deal form when KPIs weren't extracted. Each KPI has a `source` dropdown so the talent declares provenance.
- **Platform API auto-pull** (ongoing) — nightly job pulls fresh insights for posts with URLs in `deliverables[].post_urls`, captures peak metrics over 30-day window post-campaign.

### Why this unlocks the outreach engine
The single biggest lever for cold-email reply rates is citing real, specific, sourced numbers from past campaigns. After this build, the outreach AI can generate pitches like:

> "I drove 1.24M reach for Gymshark at a 7.4% ER — the campaign generated $38k in attributed sales and Gymshark renewed me for Q1 2026. Happy to walk through what worked and how it could apply to Alo Yoga."

Five new angles in `data/pitch_angles.json` fire from deal data (`past_campaign_specific_metric`, `past_campaign_brand_renewed`, `past_campaign_high_conversion`, `past_campaign_audience_overlap_proof`, `past_campaign_beat_benchmark`); three existing angles (`past_brand_direct_competitor`, `past_relationship_eligible`, `case_study_available`) draw richer merge fields from deal records. Email generator strongly prefers higher-confidence KPI sources (`platform_verified` > `brand_reported` > `third_party`) when picking which figure to cite.

### Why this powers re-engagement
Brand Discovery Search 1 reads `renewal_eligibility_date` per deal (configurable per brand: a brand that says "come back in March" sets `cool_down_override_days`) instead of a flat 180-day rule. Hard `do_not_recontact` flags block soured-deal brands forever. Outcome-based downrank filters out brands where outcome was `underperformed` or `unfulfilled`. Anti-spam de-spam extends cool-downs on no-response to avoid harassing brands.

### Honesty-floor policy
Same posture as elsewhere in the system — never fabricate. Missing metrics are omitted (no null / zero / guess). When sources disagree, prefer freshest from highest-confidence source; note discrepancy in `performance_notes`. `manually_verified_by_talent` flag distinguishes AI-extracted-but-unreviewed from talent-verified records; email generator weights verified records higher.

---

## Phase 2 — Brand Discovery & Targeting

### Output
A per-talent ranked long-list of brand candidates at `data/brand_candidates/current/{talent_id}.json`, validated against `schemas/brand_candidates.schema.json`. Folder is gitignored — the schema and spec are tracked; generated data is not.

### How it works
Two layers, both spec'd before code:

1. **Industry recommendation** (`docs/recommendation_algorithm.md`) — 5-layer score (direct affinity 60% + IAB bridge 25% + past deals 5% + preference boost 10% + policy filters) turns the talent profile into a ranked list of `industry_id`s with `why[]`.
2. **Brand discovery** (`docs/brand_discovery.md`) — 16 independent searches run in parallel, results merged by `brand_id`. A brand surfacing from multiple searches scores higher — count itself is the signal.

The 16 searches cover:

| Group | Searches | Reads |
|---|---|---|
| **Re-engagement** | 1. Previous brands eligible after cool-down | `talent.previous_brands` + dates |
| **Network expansion** | 2. Similar talents' brands<br>3. Competitors of own brands<br>4. Competitors of similar talents' brands<br>5-7. Primary / secondary / tertiary industries | `talent.similar_talent`, `brand_competitors.json`, `brand_industry_map.json`, `niche_industry_affinity.json` |
| **Affinity expansion** | 8. Parent/sibling niches<br>9. Bridged-affinity via IAB demos | `niches.json` parent chain, `niche_audience_affinity.json` + `industry_audience_affinity.json` |
| **Audience-geographic** | 10. Geographic alignment<br>11. Audience life-stage signal | `talent.audience_demographics`, `brand_industry_map.hq_country / sells_in_countries` |
| **Constraint-aware** | 12. Complementary to exclusivities<br>13. Values-aligned brands | `talent.brand_preferences.active_exclusivities`, `values_red_lines` |
| **Graph expansion** | 14. 2nd-degree network | `brand_competitors.json` traversal + roster data |
| **Momentum** | 15. Recently funded (via Exa web search)<br>16. Trending brands (via `last30days` skill) | Exa API + `last30days` skill across Reddit/X/TikTok/YouTube/HN/etc. |

### Qualification filtering
Every candidate carries a `qualification` block with score + signals (positive: active creator program, macro tier, public company, recent funding, high own-brand followers; negative: micro tier, bootstrapped, low followers, B2B vertical). Candidates below score 0.30 are kept in the file but hidden from default view.

### Brand metadata feeds qualification
`brand_industry_map.json` has been enriched with structured metadata that powers both filtering and ranking:

| Field | Coverage | Used by |
|---|---|---|
| `hq_country`, `sells_in_countries` | 290/290 | Search 10 (geo), qualification |
| `company_stage` (`bootstrapped`..`public`..`subsidiary`..`state_owned`) | 290/290 | Qualification, Search 6 inference |
| `typical_campaign_tier` (`nano`..`micro`..`mid`..`macro`..`premium`) | 290/290 | Qualification, future rate-card match |
| `creator_program_presence` (`direct`/`aspire`/`grin`/`ltk`/`shopmy`/`agency_of_record`) | 290/290 | Qualification primary signal |
| `revenue` (USD + as_of_year + source) | 181/290 (62%) | Qualification (enterprise/significant/minimal) |
| `headcount` (LinkedIn-standard bands + source) | 203/290 (70%) | Qualification |
| `social_followers` (per-platform integer counts + as_of_year) | 180/290 (62%) | Qualification (high/moderate/low own-brand follower count) |

Honest-gaps policy: fields are absent when not confident — never null, never fabricated. The full enrichment pipeline for new brands lives in `docs/brand_enrichment_workflow.md`.

### Schedule
- **Monthly cron** (1st of month, per talent): full re-run; catches new re-engagement eligibility, newly-enriched similar talents, freshly-funded brands (Search 15), and 30-day trending brands (Search 16).
- **On talent-profile save/update:** full re-run for that talent.
- **On `brand_industry_map` changes:** incremental re-run of Searches 3, 4, 5, 6, 7.
- **On-demand:** user can trigger from the UI.

### Output preservation
The orchestrator merges fresh discovery output with the previous run's workflow state. Discovery-output fields (`score`, `tier`, `sources`, etc.) are rebuilt every run; workflow-state fields (`status`, `assigned_to`, `user_notes`, `pitch_history`, `first_surfaced_at`) are **preserved**. A user-set `status: "shortlisted"` survives next month's discovery re-run intact. Immutable monthly snapshots are kept under `data/brand_candidates/runs/{talent_id}/run_{date}.json` — needed for the rising-delta / mention-velocity enhancements specced for Search 16.

### Vendor stack (v0.1, for Phase 2)
Two paid dependencies:
- **Exa** — semantic web search for Search 15 + brand enrichment lookups.
- **Anthropic SDK (Claude Haiku 4.5)** — classification + extraction throughout.

Everything else (Reddit / HN / YouTube / X / GitHub / Wikipedia / Yahoo Finance for the `last30days` and enrichment pipelines) uses free public APIs or scrapes. Deferred vendors with criteria-for-adding live in `docs/vendor_roadmap.md`.

---

## Phase 3a — Contact CRM

### Output
A per-brand contact list at `data/brand_contacts/{brand_id}.json`, validated against `schemas/brand_contact.schema.json`. The folder is **gitignored** — contacts are PII and vendor data (Apollo/LinkedIn) is licensed; only the schema and spec are tracked in the repo.

### Shared pool, per-talent pitch history
One contact pool serves the whole roster (no double-paying Apollo for the same person if two talents target the same brand). `pitch_history[]` on each contact carries `talent_id` per entry — so we know which talent pitched whom and when, with a configurable 14-day cooldown to prevent double-pitching the same person across two talents in our roster.

### Contact record sections

| Section | Fields |
|---|---|
| **Identity** | `contact_id` (slug), `brand_id`, `name.{full,first,last,preferred}`, `is_placeholder` |
| **Role** | `title`, `function` (enum: influencer_marketing / brand_partnerships / marketing / brand_management / social_media / pr_comms / creative / founder_ceo / agency_of_record / ...), `seniority` (founder / c_suite / svp / vp / director / manager / ic), `decision_role`, `decision_role_rationale`, `decision_authority_size_band` |
| **Location** | city, country (ISO α-2), timezone |
| **Channels** | `email.{address, verification_status, source, verified_at}` · `linkedin.{url, handle, last_updated, last_activity}` · `social_handles` · `phone` (rare) |
| **Tenure** | `started_at`, `previous_brand`, `is_current` |
| **Qualification** | `score` (0–1), `tier` (qualified / speculative / unqualified), `signals[]` |
| **Workflow** (preserved across re-enrichment) | `tags[]`, `notes`, `pitch_history[]`, `do_not_contact`, `opt_out_at`, `champion_for_talents[]` |
| **Enrichment meta** | `first_discovered_at`, `last_verified_at`, `verification_sources[]`, `confidence` |

### Decision-role taxonomy
A CMO at a $50B+ brand has the title but not the sign-off authority for a $5k Reel deal. The Influencer Marketing Manager 2 levels down is the real `buyer`. The simplified 5-value taxonomy captures who matters for the decision:

| `decision_role` | What they do | Typical at |
|---|---|---|
| `buyer` | Can say yes AND holds the budget for this deal size | IM Manager at mid+ brand; founder/CEO at startup |
| `influencer` (decision-shaping, not the creator role) | Has input but no authority | CMO at megabrand, senior brand manager, brand manager (runs the campaign), procurement/finance reviewer |
| `gatekeeper` | Controls access to the buyer | EA, agency-of-record account manager |
| `champion` | Internal advocate / known fan of this talent or talent type | Junior fan, friend-of-talent inside the company |
| `unknown` | Default until classified | New contacts pending LLM classification |

LLM-driven classification at Step 6 of the enrichment pipeline outputs `decision_role` + a one-line rationale visible to the user. The `decision_authority_size_band` field (separate from role) captures *what deal size* this person can sign off on (`micro` <$5k → `enterprise` $500k+). Blockers and dead-end contacts are captured via free-form `tags[]` rather than a primary role.

### Contact-qualification signals
Ranks contacts *within* a brand (separate from brand-level qualification in Phase 2):

| Direction | Signal | Source |
|---|---|---|
| (+) | `has_verified_email`, `holds_decision_role`, `tenure_at_least_1y`, `recent_linkedin_activity`, `champion_for_other_talents`, `warm_intro_available`, `matches_brand_typical_tier`, `in_target_audience_country` | Apollo + LinkedIn API + pitch_history |
| (−) | `left_brand`, `placeholder_only`, `email_bounced_recently`, `senior_executive_at_large_brand`, `unverified_email`, `no_linkedin_url`, `stale_data` | Same + verification status |

### Triggers
- **Auto:** when a brand surfaces in `brand_candidates` as `tier: primary` AND `qualification.tier ∈ [qualified, speculative]` AND no contacts file exists yet — kicks off in-flight after Brand Discovery completes.
- **Manual:** user clicks "find contacts" for a specific brand.
- **Refresh:** quarterly re-verifies emails; annual re-pulls LinkedIn data.

### Vendor stack (Phase 3 v0.1)
Three confirmed for v0.1:
- **Apollo** — primary employee lookup + email verification (~$0.20–$0.50/contact)
- **LinkedIn API** (user-provided) — freshness check, last-activity, search for contacts Apollo misses
- **Exa** — fallback for brands Apollo doesn't cover (small D2C, niche)
- **Claude Haiku** — decision-role classification + web-search extraction

Deferred to Phase 3 v2: **Hunter.io**, **Clay.com**, **RocketReach** — see `docs/vendor_roadmap.md` for criteria.

### Outreach hygiene & data handling
US project — CAN-SPAM is the primary legal frame. The structures below are standard CRM/email-marketing good practice:
- Folder gitignored — contact PII + licensed vendor data never committed.
- Opt-out / unsubscribe: `opt_out_at` + `do_not_contact: true` keep record (so we don't accidentally re-enrich and re-pitch them later) but exclude from all future outreach across the roster.
- Source disclosure: `verification_sources[]` records every vendor + date + fields they contributed — answerable in seconds if a contact asks how we got their email.
- Vendor terms: Apollo data is licensed; stays in the gitignored folder, never redistributed.
- Per-talent cooldown: 14 days between pitches to the same contact across different talents in our roster — protects deliverability and sender reputation.
- Bounce handling: hard bounces → `verification_status: bounced` permanently for that address; no retry.

### Placeholder contacts
When a target role is known to exist at a brand (e.g. "Nike must have an IM Manager") but no person is found, the pipeline writes a placeholder record (`is_placeholder: true`, name like "Unknown — Influencer Marketing Manager"). Surfaces coverage gaps as a dashboard signal so they can be filled later. Placeholders are filtered from default outreach lists but counted in the per-brand contact coverage stat.

---

## Phase 3b — Outreach

### Output
A running outreach engine that turns qualified contacts into AI-generated email sequences with reply detection, kill-on-reply across the roster, and full per-email analytics. Runs on Smartlead as the send/sequence backend; Claude generates per-step content; our app owns the angle selection, kill logic, and analytics.

### Two layers
- **Template layer** (`schemas/pitch_template.schema.json`) — sequence STRUCTURE (steps, timing, intent per step, preferred angle categories). System ships 3 default templates: `buyer-direct-pitch` (4 steps), `influencer-warm-intro` (3), `champion-activation` (2). `gatekeeper` contacts have no auto-sequence — surfaced for manual handling.
- **Enrollment layer** (`schemas/pitch_enrollment.schema.json`) — RUNNING INSTANCE of a template for a specific (talent, contact) pair, with AI-generated content per step, Smartlead identifiers, engagement events, and outcome classification.

### Angles library
[`data/pitch_angles.json`](data/pitch_angles.json) ships **37 curated angles** across 15 categories. Examples:
- `past_brand_direct_competitor` — talent has worked with a direct competitor of the target brand (strongest competitive proof; strength 0.95)
- `similar_talent_partnered_with_brand` — a similar talent in our system has partnered with this brand (precedent; strength 0.85)
- `iab_demographic_overlap` — strong IAB demographic match (quantitative audience fit; strength 0.80)
- `brand_new_product_launch` — brand recently launched, time-sensitive (strength 0.70)
- `past_relationship_eligible` — re-engagement of a past brand after cool-down (strength 0.95)
- ...plus categories for niche fit, brand momentum, geographic alignment, mutual connection, values alignment, performance proof, timeliness, creative concepts, insider observations, and role-default hooks per decision_role.

Each angle has a trigger condition (when it fires for a given talent+contact+brand combo), applicable decision roles, applicable step numbers, an example phrasing pattern the LLM adapts, and a hand-authored `authored_strength_score`. The AI generation step gets the set of APPLICABLE angles, picks one primary + optional supporting, and weaves them into the email.

### AI generation — L4 personalization (every step)
Per the v0.1 user decision, **every step in every sequence is generated per-contact** (not templated). Step 1 uses Claude Sonnet 4.7 (highest-value content); follow-up steps use Claude Haiku 4.5 (cost optimisation). Full provenance captured per email:
- Which angles were considered and which was picked
- Model + tokens + cost per generation
- Which personalization fields were merged from talent/contact/brand data
- Reasoning trace

Token budget: ~$0.027 per full 4-step sequence. 100 contacts = ~$2.70 in Claude costs.

### Step 1 manual-approval (hard rule)
**The first email of every sequence requires explicit user approval before sending.** Not configurable, not auto-bypassed, not version-dependent — this is a system invariant. Rationale: the first touch is the highest-stakes email; reply rates are driven disproportionately by step 1; once sent, it cannot be unsent.

Follow-ups (steps 2+) require approval in v0.1 too, but auto-approval for follow-ups becomes a per-talent configurable option in v0.2 (with three guardrails: validation score, tone-similarity to previously-approved content, fresh `sensitive_category` flag). Step 1 stays manual regardless of version or per-talent settings.

### Reply detection + kill logic
Smartlead fires a webhook on every reply. Our app:
1. Claude Haiku classifies reply intent: `interested` / `declined` / `out_of_office` / `unrelated` / `unsubscribe_request` / `needs_more_info` / `wrong_person_routed`
2. Extracts structured signals (asked for pricing? meeting? OoO date? routed to whom?)
3. Kills the active sequence AND any other active sequences for the same contact across the roster
4. `interested` → hot lead in talent's UI; `OoO` → pause + auto-resume; `unsubscribe_request` → permanent `do_not_contact: true`

### Headline metric: reply rate
Per the v0.1 user decision, **reply rate (replied ÷ delivered) is the headline UI metric** — most reliable signal in 2026. Apple Mail Privacy Protection has made open rates noisy (auto-loads tracking pixels), so `engagement_summary.human_opens` filters out likely-MPP events. Raw open rate is captured but flagged noisy.

### Agency-level sender (not per-talent)
Outreach emails are sent by the talent's **agency** in the agent's name (e.g. `sarah@nativeagency.com`), not from per-talent mailboxes. Voice: **agent-led on-behalf-of talent** — "I'm Sarah from Native Agency — I represent Jane Doe, who drove 1.24M reach for Gymshark." The agency's sender mailbox + DNS records + 2-4 week warmup are a one-time Phase 0 setup (`docs/agency_setup_workflow.md`); all subsequent talent onboarding plugs into the pre-warmed mailbox. v0.1 = single agent / single agency; v2 = multi-agent within agency. All 42 pitch angles use agent-led on-behalf-of voice with `{talent_name}` as a required merge field.

### Email-only in v0.1
Phase 3b v0.1 sends **email only**. LinkedIn outreach (DMs / InMails / connection requests as part of a sequence) is deferred to v2. The pitch_template schema restricts `channel` to `email`; the orchestrator rejects any non-email step. LinkedIn API is still in v0.1 — but for **contact enrichment** (verifying Apollo data freshness, finding contacts Apollo misses), not for sending. When v2 adds LinkedIn-channel sending we'll evaluate vendors (Sales Nav API vs Closely / Expandi / La Growth Machine), automation-policy compliance, and per-talent LinkedIn account warmup.

### Vendor stack (Phase 3b v0.1)
- **Smartlead** — send + sequence + warmup + reply detection (~$94/mo Pro per talent mailbox)
- **Claude (Anthropic SDK)** — content generation + reply classification (~$0.027 per full sequence)

That's the entire vendor footprint for Phase 3b. Resend was considered but rejected — their ToS prohibits cold outreach (transactional API). Hunter.io / Clay.com / RocketReach deferred to v2 if Apollo coverage gaps emerge.

### Analytics — every email tracked, every angle measured
[`scripts/analyze_outreach.py`](scripts/analyze_outreach.py) rolls every step record into A/B sliceable aggregates:

| Slice | What it answers |
|---|---|
| by_angle | Which angles have the best reply rate |
| by_angle_pair | Whether primary+supporting combinations beat singletons |
| by_decision_role | Which angles work for buyers vs influencers vs champions |
| by_template | Which templates convert best |
| by_step_number | When in the sequence replies happen |
| by_brand_tier / brand_industry | Which brand profiles respond |
| by_talent | Which of our roster's talents convert best |
| by_send_dow / send_hour | Day-of-week / time-of-day effects |
| by_subject_pattern | Length / question / emoji effects |
| by_sender_domain | Per-domain inbox placement |

Each slice computes: sent, delivered, reply rate, positive reply rate, human open rate (MPP-filtered), click rate, bounce rate, mean time-to-reply, total cost, cost per positive reply.

**v0.1 explicit non-goal:** the analyzer does NOT auto-update `pitch_angles.json` `authored_strength_score`. Output is for human review only. Users edit angles manually as they learn. Closed-loop auto-tuning is a v2 deliverable.

---

## Phase 4 — Deal Lifecycle

### Output
A pipeline of active deals at `data/deals/{deal_id}.json` (gitignored — contracts, invoice amounts, payment records). Each deal moves through 5 stages from a Phase 3b `interested` reply through to a paid + archived brand deal. Validated against `schemas/deal.schema.json`.

### The 5-stage lifecycle

```
LEAD ──► PROPOSAL ──► CONTRACT ──► DELIVERY ──► CLOSE ──► (archive to Phase 1.5)
```

| Stage | Substages | Data captured |
|---|---|---|
| **1. LEAD** | new_lead → initial_call_scheduled → initial_call_completed → brief_received → qualified / disqualified | Discovery call notes, brand brief (text or PDF), qualification decision + rationale |
| **2. PROPOSAL** | proposal_drafting → proposal_sent → under_review → negotiation → terms_agreed / lost | Deliverables, fee_usd, usage_rights_granted, exclusivity, negotiation_log (chronological back-and-forth), agreed final terms summary |
| **3. CONTRACT** | drafting → in_review_brand / in_review_talent → revisions → executed / failed | Draft + final PDFs, e_sign_provider (manual / docusign / pandadoc / hellosign), signed_at timestamps both sides, amendment log |
| **4. DELIVERY** | pre_production → content_in_production → pending_brand_approval → revisions_requested → approved_for_posting → live → performance_window | Production schedule, products shipped, content drafts versioned per deliverable, brand approval log, posting schedule with URLs, performance capture window |
| **5. CLOSE** | invoice_sent → invoice_paid → post_campaign_reporting → archived | Invoice ID + amount + provider (manual / stripe / xero / quickbooks), payment received timestamp + method, final performance report, final KPI snapshot, archive trigger |

### State machine
Every transition is governed by an explicit rule set in `docs/deal_lifecycle_workflow.md` § State machine. The orchestrator rejects any invalid transition (with a force-override flag for unusual cases like resurrecting a `lost` deal). `stage_history[]` is an append-only audit log of every transition with timestamp + agent + optional note.

### Structured loss reasons
Any non-archived terminal state populates a `loss` block with:
- `reason` enum: `budget` / `timing` / `competitor_won` / `internal_pivot` / `talent_no_fit` / `terms_disagreed` / `unresponsive` / `compliance_block` / `other`
- `lost_at_stage` (which stage we were in when the deal died)
- `competitor_brand` (if reason=competitor_won)
- Free-text `notes`

Loss reason × lost_at_stage cross-tab in the analyzer surfaces funnel diagnostics ("30% of LEAD losses are `unresponsive` — discovery cadence too slow").

### Auto-archive on close
When `payment_received_at` is set AND `final_kpis` is captured AND `final_performance_report_attachment_id` is set, the orchestrator automatically:
1. Builds a Phase 1.5 brand_deal record from the deal's data (deliverables, fee, KPIs, etc.)
2. Sets the new brand_deal's `originated_from_pitch_enrollment_id` (closes the outreach → deal loop)
3. Sets the brand_deal's `archived_from_deal_id` to this deal's id (bidirectional link)
4. Writes to `data/brand_deals/{talent_id}.json`
5. Sets this deal's `archived_to_brand_deal_id` + `archived_at`
6. Transitions to `stage: "archived"`, `is_terminal: true`, `is_won: true`

Single source of truth: active deals live in Phase 4; historical deals live in Phase 1.5. No drift.

### Integration with Phase 3b outreach
Reply classification `outcome="interested"` triggers deal creation in `stage: "lead"`:
- `originating_enrollment_id` = the pitch enrollment that won the reply
- `primary_contact_id` = the contact who replied
- `assigned_agent_id` = the agent who sent the outreach
- `outcome_classification.extracted_signals` pre-seeds substage (e.g. `asked_for_meeting: true` → `substage: "initial_call_scheduled"`)

This closes the full **funnel: emails sent → delivered → replied → interested → deal created → won**. The analyzer can now compute per-angle / per-template / per-decision-role conversion-to-won-deal rates, not just reply rates.

### Notifications + reminders
Every deal carries `next_action` (free-text) + `next_action_due_at` (timestamp). A daily cron surfaces overdue actions in the agent's morning summary. The orchestrator auto-updates `next_action` on stage transitions (e.g. on `proposal_sent`, sets next_action to "Follow up in 3 days if no reply" with `next_action_due_at: proposal_sent_at + 3d`).

### v0.1 vs v2 vendor integrations
**v0.1 — manual:** contracts and invoices are tracked as PDF attachments + manually-set timestamps. `e_sign_provider: "manual"`, `invoice_provider: "manual"`.

**v2 — API-integrated:** schema already has `e_sign_provider` / `e_sign_envelope_id` and `invoice_provider` / `invoice_id` fields. When v2 wires up DocuSign / PandaDoc / Stripe / Xero / QuickBooks, webhooks auto-populate the timestamp fields and upload signed PDFs. See `docs/vendor_roadmap.md` § Phase 4 vendor integrations.

### Storage
`data/deals/{deal_id}.json` per deal. Gitignored. Filesystem JSON for v0.1; production should move to Postgres (workflow state) + S3 (attachments) at build time.

---

## Phase 4.5 — Discovery Call Prep

### Output
A versioned prep pack per deal at `data/deals/{deal_id}/prep_packs/v{N}.json` (gitignored). Each version bundles three deliverables — **agenda**, **briefing notes** (agent-only), **slide deck** — auto-drafted by a 3-pass Claude Sonnet pipeline + Exa external research, then iteratively refinable via natural-language feedback. Validated against `schemas/discovery_prep_pack.schema.json`.

### Trigger + locked-in decisions
- **Fires on:** `deal.substage = initial_call_scheduled` (transitioned within Phase 4 LEAD stage)
- **Agent solo on call:** talent doesn't attend discovery calls. Briefing = internal cheat-sheet; slides position talent to brand.
- **One deck source, two output variants:** single `slides[]` JSON renders `deck-live.html` (sparse, big visuals — screen-shared on call) + `deck-leave-behind.html` (denser, written rationale — sent post-call). Plus a separate `speaker-notes.md` for the agent's second-screen reference.
- **LLM auto-drafts everything end-to-end:** the agent owns review + iteration, not the blank-page draft.
- **V1 stays locked unless agent asks:** upstream data drift (talent KPIs, brand context) is detected and surfaced as informational, but never triggers auto-regen.
- **Old versions retained:** v1, v2, v3… all queryable from `deal.lead.discovery_prep_pack_ids[]`. `latest_prep_pack_id` points to current.

### Generation pipeline
```
Trigger: substage → initial_call_scheduled
  │
  ▼ Agent (optional) provides pre_generation_guidance text
  ▼ Gather context (Phase 1 talent + 1.5 brand_deals + Phase 2 candidate + 3a contact + 3b enrollment + pitch_angles + agency branding)
  ▼ Exa external research (3-5 queries: brand campaigns, news, contact background, competitor landscape)
  ▼ Sonnet Pass 1: briefing_notes  (cached: context reused downstream)
  ▼ Sonnet Pass 2: agenda
  ▼ Sonnet Pass 3: slides[]
  ▼ Validate against schema
  ▼ Render artefacts (Jinja2 HTML + Puppeteer PDF + slide skill PPT + markdown writers)
  ▼ Write v{N}.json + v{N}_artifacts/
  ▼ Surface in agent's morning summary 24h before call
```

### The 3 outputs

**Agenda** (`agenda.md` artefact) — single-page, 45-min default with 6 sections: **Introductions → Brand overview → Talent overview → Objectives → Opportunities → Next steps**. LLM-customised per deal (durations rebalanced, talking points tailored). The **Objectives** section internally maps to SPICED's situation/pain/impact/critical-event from B2B sales discovery — but those framework terms never surface in any client-facing artefact; the section is framed plainly as "what you're trying to achieve, current friction, why now." Briefing notes carry the agent's structured discovery questions for this section.

**Briefing notes** (`briefing-notes.md` artefact, agent-only) — multi-section markdown:
- Deal summary (citing originating reply verbatim)
- About brand (Phase 2 + Exa research, with provenance per claim)
- About contact (Phase 3a + pitch_history signals)
- About talent for this call (relevant past work, KPIs to lead with)
- Fit hypothesis (synthesised from top-scoring pitch_angles)
- Likely objections + responses (patterns from past `objection` outcomes)
- Red flags (talent red_lines vs brand)
- Questions to ask + likely questions from them with prepared answers
- **Commercial range** computed from comparable past brand_deals (low/high USD + rationale + comparable deal IDs — internal only, not shown to brand on call)

**Slide deck** — structured `slides[]` JSON. Default 10 slides with `type` enum driving layout: title / context / talent_overview / audience_snapshot / recent_work / brand_observation / fit_angle / case_study / proof_point / process / next_steps. Each slide has `live_body` (sparse, big-visual), `leave_behind_extension` (denser, written), `speaker_notes` (agent voiceover), `sources[]` (citations for every factual claim per honesty-floor).

Three rendered artefacts from one source: `deck-live.html|pdf`, `deck-leave-behind.html|pdf`, `speaker-notes.md`. PPT via the slide skill.

### Natural-language feedback regeneration loop
After v1 is generated, the agent iterates:

> "Slide 4 audience claim feels overstated — tone it down and add the as-of date. Drop the sustainability angle entirely, brand told me on the intro email they're focused on performance not values. Beef up the commercial range — I think we're underselling for this scope."

Captured as `generation.regeneration_feedback`. LLM consumes: original context + v1 full pack + feedback → v2 with `parent_version: 1`. v1.is_latest flips to false; v2.is_latest = true. Old versions stay queryable.

**Section-targeted regen:** "Regenerate just the objections" → `target_sections: ["briefing.likely_objections"]`. "Redo slides 4 and 7" → `target_sections: ["slides[3]", "slides[6]"]`. Untargeted sections carry forward unchanged from parent — faster + cheaper.

### Slide skill integration
The slide skill (provided separately) produces editable HTML output with two interaction modes:
1. **Direct edit** — agent types into slide HTML in-place; saves update `slides[N]` and append to `agent_edits[]`. No new version.
2. **Natural-language feedback per slide** — "make this punchier"; triggers per-slide LLM regen → produces v(N+1) with `trigger: agent_per_slide_regenerate`.

Orchestrator-side contract: `{slides, branding, mode}` in → `{html_path, pdf_path, pptx_path, on_edit, on_feedback}` out. v0.1 fallback before skill is wired: Jinja2 HTML + Puppeteer PDF; PPT marked `status: pending`.

### Branding from Phase 0
Logo, primary/secondary/accent colors, font families, tagline — all pulled from `agency_profile.branding` (captured at Phase 0 Step 1.5). Rebrand once → propagates to all future prep packs on next render. Single source of truth.

### Cost profile
Per-pack: ~3 Sonnet passes × ~15k input tokens (heavily cached) + ~7k output tokens + 3-5 Exa queries. Estimated $0.10-0.30 per generation. At 50 active deals × 3 regens each = ~$15-45/mo per agency. Manageable. Per-deal cost cap considered for v0.2.

### Storage
```
data/deals/{deal_id}/
  prep_packs/
    v1.json
    v1_artifacts/{deck-live.html, deck-leave-behind.html, deck-live.pdf, deck-leave-behind.pdf, speaker-notes.md, briefing-notes.md, agenda.md, deck.pptx}
    v2.json
    v2_artifacts/...
```
All gitignored.

---

## Phase 4.6 — Proposal Pack

### Output
A versioned commercial proposal per deal at `data/deals/{deal_id}/proposal_packs/v{N}.json` (gitignored). Each version bundles the agent-uploaded context artefacts, the LLM's commercial proposal + agent's confirmation event, and the rendered slide deck (live + leave-behind + speaker notes). Validated against `schemas/proposal_pack.schema.json`.

### Trigger + locked-in decisions
- **Fires on:** agent clicks "Draft proposal" while deal is in `proposal_drafting` substage. Manual trigger (not auto-fire on substage change) — higher commercial stakes than discovery prep.
- **Uploads in v0.1:** PDF (pypdf), Word (python-docx), text/markdown. **v2** adds external transcript-link references (Otter/Fireflies/Grain — URL refs only, no in-house transcription).
- **Hybrid discovery → proposal bridge:** agent dumps notes (or uploads transcript file) → LLM extracts structured `discovery_debrief` → agent reviews + edits + confirms → proposal generation fires from confirmed debrief.
- **Commercial gate (HARD):** LLM proposes deliverables + fee + usage rights + exclusivity + timeline + payment terms with rationale per field. Agent must explicitly confirm before slides render. On confirm, values copy into `deal.proposal.*` (canonical commercial source-of-truth).
- **Three output variants:** live HTML + leave-behind HTML + speaker notes (same as discovery prep). Proposals are usually sent for review but walked through in follow-up calls.
- **Forks from discovery:** talent_overview, audience_snapshot, recent_work, fit_angle slides lift from `deal.lead.latest_prep_pack_id`. Each forked slide carries `forked_from_prep_slide_id` for traceability.
- **Negotiation tie-in:** brand pushback → entry in `deal.proposal.negotiation_log[]` with `proposal_pack_version` → agent triggers `negotiation_response` regen → new version's `generation.negotiation_log_entry_ref` points back. Bidirectional.

### 5-stage generation pipeline
```
Trigger: agent clicks "Draft proposal" (substage = proposal_drafting)
  │
  ▼ A. Context augmentation: uploads parsed (pypdf/python-docx) +
  │    LLM-summarised + relevance-tagged as context_artefact entries
  ▼ B. Hybrid debrief extraction: LLM extracts 10 structured fields
  │    (objectives_heard, pain_points, critical_event, scope/timing/budget
  │    signals, exclusivity_signals, usage_rights_signals, decision_process,
  │    red_flags_surfaced) — each with confidence. Agent reviews + confirms.
  │    Writes to deal.lead.discovery_debrief.
  ▼ C. Commercial gate (HARD): LLM proposes deliverables + fee + usage_rights
  │    + exclusivity + timeline + payment_terms + exclusions with rationale.
  │    Agent confirms (or overrides). On confirm, values copy into
  │    deal.proposal.*. ─── SLIDES CANNOT RENDER UNTIL CONFIRMED ───
  ▼ D. 3-pass Sonnet slide generation: executive summary → slides[]
  │    (forks discovery slides + adds proposal-specific) → speaker notes.
  ▼ E. Render: live HTML + leave-behind HTML + PDFs + speaker-notes.md
  │    + commercial-summary.md + PPTX (via slide skill).
  ▼ Write data/deals/{deal_id}/proposal_packs/v{N}.json + v{N}_artifacts/
  ▼ NL feedback regen loop (v2, v3, ...)
  ▼ Agent marks "ready to send" → deal.proposal.proposal_attachment_id +
    proposal_sent_at; substage → proposal_sent
```

### Default slide structure (15 slides live; ~22-25 leave-behind)

| # | Section | Type | Forked? |
|---|---|---|---|
| 1 | Title | title | New |
| 2 | Executive summary | executive_summary | New |
| 3 | **Objectives recap** (lifts `discovery_debrief.objectives_heard` verbatim — "here's what we heard you say") | objectives_recap | New |
| 4 | Talent overview | talent_overview | **Forked from prep** |
| 5 | Audience snapshot | audience_snapshot | **Forked from prep** |
| 6 | Recent work | recent_work | **Forked from prep** |
| 7 | Our recommendation | recommendation | New |
| 8 | Deliverables | deliverables | New |
| 9 | Timeline | timeline | New |
| 10 | Investment | investment | New |
| 11 | Usage rights | usage_rights | New |
| 12 | Exclusivity | exclusivity | New |
| 13 | What's not included | exclusions | New |
| 14 | How we work | agency_process | New |
| 15 | Next steps | next_steps_proposal | New |

### Storage
```
data/deals/{deal_id}/
  prep_packs/                # Phase 4.5
  proposal_packs/            # Phase 4.6
    v1.json
    v1_artifacts/{proposal-live.html, proposal-leave-behind.html, proposal-live.pdf, proposal-leave-behind.pdf, speaker-notes.md, commercial-summary.md, proposal.pptx}
    v2.json
    v2_artifacts/...
  context_uploads/           # Phase 4.6 raw uploads
    ctx_abc_brand_brief.pdf
    ctx_def_discovery_notes.docx
```
All gitignored. File caps v0.1: 25MB/file, 100MB/deal. Larger files → external URL reference via `context_artefact.external_url`.

### Cost profile
Per-pack: 4-5 Sonnet passes (artefact summary + debrief extraction + commercial proposal + executive summary + slides + speaker notes), heavily cached. ~25-35k input tokens + ~12-15k output tokens. Estimated $0.30-0.60 per generation. Iteration cost scales with negotiation rounds.

---

## Phase 4.7 — Contract Pack

### Output
A versioned contract draft per deal at `data/deals/{deal_id}/contract_packs/v{N}.json` (gitignored). Each version bundles merge field values (with confidence + source per field), conditional clause decisions (with applicability rationale), narrative sections (LLM-drafted), the composed contract markdown, the legal review gate state, and rendered artefacts (markdown source-of-truth + Word .docx + PDF). Validated against `schemas/contract_pack.schema.json`.

### Trigger + locked-in decisions
- **Fires on:** agent clicks "Draft contract" while deal is in `contract_drafting` substage. Manual trigger (higher legal stakes than proposal — no auto-fire).
- **Template lives per-talent:** `talent.contract_template` block captured in Phase 1 onboarding **Step 7.5**. Markdown source + merge field definitions + clause applicability rules + narrative placeholders + governing law defaults + optional external `legal_reviewer_id`.
- **Markdown with merge fields + conditionals + narrative placeholders** as source-of-truth: `{{merge_field}}` for substitution, `{{#if clause_id}}...{{/if}}` for conditional clauses, `{{narrative_*}}` for LLM-drafted bounded sections. Rendered to Word .docx + PDF.
- **Hard legal review gate:** Word + PDF artefacts cannot render until `legal_review.approved_at` is set. Any edit post-approval resets the gate (re-approval required) unless agent flags `trivial_edit_override`. Strict — contract stakes warrant it.
- **LLM scope: merge + narrative + conditional clauses; NOT full clause rewriting.** Predictable behaviour, bounded legal risk.
- **Agency starter templates** (gitignored) in `data/contract_template_starters/` — Phase 1 onboarding flow copies a starter into the talent's `contract_template.markdown_source` for editing; `based_on_starter_template_id` tracks provenance.

### 7-stage generation pipeline
```
Trigger: agent clicks "Draft contract" (substage = contract_drafting)
  │
  ▼ A. Context augmentation: uploads parsed (pypdf/python-docx) +
  │    LLM-summarised. Critical: brand legal entity info (W-9 /
  │    company registration). Optional: brand-requested clauses,
  │    prior contracts, brand redlines.
  ▼ B. Merge field extraction: LLM extracts every {{merge_field}}
  │    from declared sources (talent.billing_entity / agency_profile /
  │    deal.proposal.* / uploaded artefacts / agent input). Each value
  │    tagged with confidence + source. Low-confidence on required
  │    fields surfaces as blocking_issue.
  ▼ C. Conditional clause evaluation: LLM decides include/exclude
  │    per {{#if}} block based on context (GDPR if EU brand;
  │    exclusivity if duration_days > 0; IP-assignment if
  │    co_created_product in additional_compensation; etc.).
  ▼ D. Narrative drafting: LLM fills {{narrative_*}} placeholders
  │    (scope_of_work, approval_process, etc.) from declared context
  │    paths with tone guidance + word-count caps.
  ▼ E. Compose: template + merge values + clause decisions +
  │    narratives → composed_markdown (canonical source-of-truth).
  ▼ F. HARD LEGAL REVIEW GATE: agent (or legal_reviewer_id) reviews
  │    every value/decision/narrative; edits log + reset gate; on
  │    approve, legal_review.approved_at set.
  │    ─── WORD + PDF CANNOT RENDER UNTIL APPROVED ───
  ▼ G. Render: composed.md → contract.docx (python-docx) +
  │    contract.pdf (Puppeteer/pandoc). deal.contract.draft_
  │    contract_attachment_id auto-set to the PDF.
  ▼ Agent sends to brand + talent (v0.1 manual; v2 e-sign)
  ▼ NL feedback regen → v2, v3, ... (incl. brand_redline_response)
```

### Schema architecture
- `merge_field_values[]` — every field with `confidence` (high/medium/low/missing), `source` (10-value enum: talent_profile / talent_billing_entity / talent_working_terms / agency_profile / deal_proposal / discovery_debrief / context_artefact / agent_input / computed / default), `needs_review` flag, agent override capture.
- `conditional_clause_decisions[]` — each `{{#if}}` block's decision with `decided_by` (template_default / llm / agent), `applicability_rationale`, agent override capture.
- `narrative_sections[]` — LLM-drafted content + `sources[]` (which context paths it drew from) + word count + agent edit tracking.
- `legal_review.blocking_issues[]` — auto-populated from low-confidence/missing required fields + agent-flagged sections. Gate cannot pass until empty.
- `legal_review.previous_approvals[]` — full audit trail of approval-edit-reapprove cycles with `reset_reason`.

### Integration
- **`talent.contract_template`** (Phase 1 Step 7.5) — template source-of-truth: markdown + merge_field_definitions + clause_applicability_rules + narrative_placeholders + governing law defaults + optional external legal_reviewer_id.
- **`talent.billing_entity`** — legal entity merge fields pull from here (legal_name, country, tax_id, address, company_number). Single source-of-truth.
- **`deal.proposal.*`** (Phase 4.6) — confirmed commercials seed contract merge fields (fee_usd, deliverables, usage_rights_granted, exclusivity, additional_compensation, payment terms).
- **`deal.contract.draft_contract_attachment_id`** (Phase 4 deal record) — auto-populated from latest contract pack PDF on Stage G render.
- **`deal.contract.amendment_log[]`** — post-execution amendments use `trigger: amendment_request` to write here.

### Storage
```
data/deals/{deal_id}/
  prep_packs/                # Phase 4.5
  proposal_packs/            # Phase 4.6
  contract_packs/            # Phase 4.7
    v1.json
    v1_artifacts/{contract.md, contract.docx, contract.pdf}
    v2.json
    v2_artifacts/...
  context_uploads/           # shared across 4.6 + 4.7
```
All gitignored. Same file caps: 25MB/file, 100MB/deal.

### Cost profile
Per-pack: 4-6 Sonnet passes (artefact summary + merge extract + clause evaluate + narrative draft + compose). Heavily cached from proposal pack context. ~30-40k input tokens + ~10-15k output tokens (less than proposal — contract is more deterministic). Estimated $0.20-0.40 per generation. Typical deal: 1-3 versions (less iteration than proposal — once approved, redlines trigger targeted regen, not full rebuild).

---

## Phase 4.8 — Invoice Pipeline

### Output
Versioned invoice packs per deal at `data/deals/{deal_id}/invoice_packs/seq{N}_v{M}.json` (gitignored). Multi-invoice from v0.1 (e.g. 50/50 NET-30 produces 2 packs). Each pack: merge field values + line items + amounts + composed markdown + payment state + rendered PDF. Validated against `schemas/invoice_pack.schema.json`. The deal's `close.invoice_schedule[]` is the LLM-parsed payment plan that drives generation; `close.invoice_pack_ids[]` is the flat FK list of all packs; `close.all_invoices_paid_at` gates auto-archive.

### Trigger + locked-in decisions
- **Three layers**: detection (cron polls platform APIs → agent confirms post matches) → generation (LLM parses contract.payment_terms → schedule → per-entry invoice_pack at trigger) → tracking (per-invoice payment_state with overdue cron).
- **v0.1 detection: IG + TikTok via direct platform APIs** (Meta Graph + TikTok Display). Other platforms via agent manual URL entry. v2 = Phyllo unified API for YouTube/LinkedIn/X/podcast/Substack.
- **Hybrid detection flow**: cron scores candidates via time_window + brand_handle + campaign_hashtag + content_type signals (≥80 strong suggest / 50-79 weak / <50 log-only); agent confirms each match before `posted_at` is set.
- **Multi-invoice from v0.1**: LLM auto-parses `contract_pack.commercial_proposal.payment_terms` (free-text like "50/50 NET-30") into structured `invoice_schedule[]`; one-time agent confirmation gate; schedule locks. Each entry has trigger_condition enum (contract_executed / first_post_live / all_deliverables_live / specific_date / manual).
- **Agency-wide invoice template** captured in Phase 0 Step 5.5. Talent billing entity pulls from `talent.billing_entity`; brand entity from `contract_pack.context_snapshot.brand_legal_entity_at_gen`.
- **Soft agent gate**: agent reviews rendered PDF + can edit before send; sending IS the approval (no separate "approve" event). Sent invoices immutable — edits create new versions.
- **Payment tracking v0.1**: agent sets `payment_received_at` manually + daily overdue cron notifies for follow-up. v2: Stripe/Xero/QuickBooks webhook auto-populates.

### Detection layer
```
Cron every 15min (stories) / 1hr (other) for active DELIVERY deals:
  For each unmatched posting_schedule[] entry:
    Query Meta Graph API (IG) or TikTok Display API for recent posts
    Score candidates against expected deliverable:
      time_window (±48h)       40 pts
      brand_handle (@brand)    30 pts
      campaign_hashtag         20 pts
      content_type match       10 pts
    ≥80 = strong suggest in UI; 50-79 = weak suggest; <50 = log only
    Agent confirms → posted_at + post_url + posted_detection block set
  When ALL posting_schedule[] entries have posted_at:
    → substage = performance_window
    → evaluate invoice_schedule[] for trigger fires
```

### Generation layer
```
Schedule parse (once per deal, on contract_executed_at):
  LLM input:  "50% upon contract execution, 50% upon final delivery; NET-30"
  LLM output: [{seq:1, %:50, trigger:contract_executed, terms:30, desc:"..."},
               {seq:2, %:50, trigger:all_deliverables_live, terms:30, desc:"..."}]
  Agent confirms → schedule locks

Per invoice pack (fires when schedule entry's trigger met):
  Stage A: Deterministic merge field extraction (talent.billing_entity +
           agency_profile + contract_pack.brand_legal_entity + computed
           invoice_number / dates / line_items / amounts)
  Stage B: Optional LLM narrative for {{narrative_line_items}} (0-1 passes)
  Stage C: Compose markdown
  Stage D: Render PDF (Puppeteer or pandoc) — no Word artefact
  Stage E: Agent review (soft gate — edits regenerate; send = approve)
           sent_at set → payment_state.status: draft → sent → due_at computed
```

### Tracking layer
- Per-invoice `payment_state` with status enum: `draft` / `sent` / `viewed_by_brand` (v2) / `paid` / `overdue` / `disputed` / `void`
- Daily overdue cron: any invoice where `due_at < now AND status: sent` → notify agent + append to `payment_reminder_log[]`. Cadence: day 1, then every 7 days.
- v0.1: agent manually sets `payment_received_at` + `payment_method` + `payment_reference` + optional `reconciliation_note`
- v2: Stripe webhook on `invoice.paid` auto-populates; schema already shaped via `external_invoice_id` + `payment_reference` fields

### Integration
- **Phase 0 `agency_profile.invoice_template`** — agency-wide template (markdown source, numbering format, tax handling, payment instructions). Captured Phase 0 Step 5.5.
- **Phase 1 `talent.billing_entity`** — FROM party on every invoice.
- **Phase 1 `talent.platforms[]`** — oAuth tokens for Meta Graph + TikTok Display polling.
- **Phase 4.6 `deal.proposal.fee_usd` + `deliverables[]`** — total + per-deliverable references for line items.
- **Phase 4.7 `contract_pack.commercial_proposal.payment_terms`** — LLM parse source.
- **Phase 4.7 `contract_pack.context_snapshot.brand_legal_entity_at_gen`** — TO party on every invoice.
- **`deal.delivery.posting_schedule[].posted_detection`** — detection provenance per match.
- **`deal.close.all_invoices_paid_at`** — computed; gates auto-archive.
- **Phase 4 CLOSE substages** — `invoice_sent` = at least one pack sent; `invoice_paid` = all schedule entries paid. Substage transitions driven by aggregate state.

### Storage
```
data/deals/{deal_id}/
  invoice_packs/
    seq1_v1.json + seq1_v1_artifacts/{invoice.md, invoice.pdf}
    seq2_v1.json + seq2_v1_artifacts/{invoice.md, invoice.pdf}
    seq2_v2.json + seq2_v2_artifacts/...  # revision
```
All gitignored. Naming includes seq + version so both visible in filename.

### Cost profile
**Per-pack LLM:** $0.05-0.15 (much lighter than other packs; often 0 LLM passes).
**Per-deal LLM:** one schedule parse on contract execution (~$0.02) + per-invoice generation.
**Platform APIs (v0.1):** Meta Graph free; TikTok Display free.
**Phyllo (v2):** ~$50-200/creator/month for unified API across YouTube/LinkedIn/X/podcast/Substack.
