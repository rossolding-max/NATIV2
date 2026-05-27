# Proposal Pack Workflow (Phase 4.6)

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the proposal pack pipeline — the artefact for Phase 4 PROPOSAL stage. Forks structured content from the Phase 4.5 discovery prep pack and adds proposal-specific commercial sections. Gated on the agent explicitly confirming pricing + deliverables.

**Pairs with:**
- `schemas/proposal_pack.schema.json` — the data contract.
- `docs/discovery_prep_workflow.md` (Phase 4.5) — the upstream artefact whose talent_overview / audience_snapshot / recent_work slides fork into the proposal.
- `docs/deal_lifecycle_workflow.md` (Phase 4) — PROPOSAL substage fires this; `deal.proposal.*` fields are populated on commercial gate confirmation; `negotiation_log[]` ↔ proposal_pack version bidirectional link.
- `docs/agency_setup_workflow.md` (Phase 0 Step 1.5) — agency branding is required input to renderer.
- `docs/vendor_roadmap.md` — pypdf + python-docx (v0.1 file parsing); Otter/Fireflies/Grain (v2 transcript link references).

## Goal

Turn the discovery call's learnings + the brand's brief + anything else relevant the agent has into a tight, sellable, *citable* proposal deck the brand can take internally and sign off on. Locked-in design decisions:

1. **Hybrid discovery → proposal bridge** — agent dumps free-form notes (or uploads transcript), LLM extracts structured debrief, agent reviews + edits before the proposal can fire. Best balance of speed + signal + verifiability.
2. **Commercial gate before slides render** — LLM proposes deliverables + fee + usage rights + exclusivity + timeline + payment terms with rationale per field. Agent must explicitly confirm before slides generate. Forces the agent to own the commercial decision rather than rubber-stamp.
3. **Three output variants** — live + leave-behind + speaker notes, same as discovery. Proposals are usually sent but agents do walk brands through them in a follow-up call.
4. **Versioned with negotiation tie-in** — each version bidirectionally links to `deal.proposal.negotiation_log[]`. Brand pushback creates a log entry → triggers v(N+1) targeted at affected sections.
5. **Forks from discovery** — talent_overview, audience_snapshot, recent_work, fit_angle slides lift from the source prep pack. Re-render only if discovery context has evolved.

## When it fires

| Trigger | Behaviour |
|---|---|
| Agent clicks "Draft proposal" on a deal in `proposal_drafting` substage | v1 generation pipeline starts. Higher-stakes than discovery prep — kept manual (no auto-fire on substage transition). |
| Agent requests regenerate (full pack) | New version v(N+1) with `regeneration_feedback`. Parent retained. |
| Agent requests regenerate (sections / slides) | Same with `target_sections`. Untargeted carry from parent. |
| Brand pushback recorded in `deal.proposal.negotiation_log[]` | Agent action creates a `negotiation_response` regen. The new version's `generation.negotiation_log_entry_ref` points back to the log entry that triggered it. Closes the audit loop. |
| Direct slide edit via slide skill | Logged in `agent_edits[]`. No new version. |
| Commercial override post-confirmation | If agent edits `commercial_proposal.confirmed_*` AFTER initial confirmation, this is a `commercial_override` agent_edit AND re-syncs `deal.proposal.*` AND typically triggers a slide-section regen. |

## The 5-stage pipeline

```
Trigger: agent clicks "Draft proposal"
  │
  ▼ STAGE A — Context augmentation
  │  Agent uploads files via the UI:
  │   · brand brief (PDF / Word / text)
  │   · discovery call notes (markdown / text)
  │   · call transcript file (text — or v2: URL to Otter/Fireflies/Grain)
  │   · reference material (competitor examples, mood boards, etc.)
  │  Each file parsed:
  │   · .pdf → pypdf text extraction
  │   · .docx → python-docx text extraction
  │   · .txt / .md → text reader
  │   · external URL (v2) → stored as reference, no extraction
  │  LLM summarises each → context_artefact with:
  │   · type (brand_brief / discovery_call_notes / call_transcript /
  │     reference_material / competitor_example / internal_memo / other)
  │   · role (primary_input / supplementary / reference)
  │   · llm_summary (compressed for downstream prompts)
  │   · llm_extracted_signals (optional structured extraction)
  │  Agent reviews summaries, can retag relevance, exclude artefacts.
  │  Stored: data/deals/{deal_id}/context_uploads/{artefact_id}_{filename}
  │
  ▼ STAGE B — Discovery debrief extraction (hybrid)
  │  Agent's post-call notes (or uploaded transcript) → LLM extracts:
  │   · objectives_heard — what brand wants to achieve
  │   · pain_points — current friction with creator partnerships
  │   · critical_event — why now; what's the trigger
  │   · scope_signal — campaign size / ambition hints
  │   · timing_signal — when they need to act
  │   · budget_signal — range / cap / "flexible" / etc.
  │   · exclusivity_signals — competing creators / category concerns
  │   · usage_rights_signals — paid social / whitelisting hints
  │   · decision_process — who else needs to sign off; how
  │   · red_flags_surfaced — anything that conflicts with talent values
  │  Each field carries a `confidence: high | medium | low` flag.
  │  Agent reviews the structured block; edits inline; confirms.
  │  → Confirmed debrief writes into deal.lead.discovery_debrief
  │  → discovery_debrief.confirmed_at + confirmed_by_agent_id set
  │
  ▼ STAGE C — Commercial proposal (HARD GATE)
  │  LLM consumes: deal context + context_artefacts + discovery_debrief
  │   + briefing's commercial_range + comparable brand_deals
  │  LLM proposes (with rationale per field):
  │   · deliverables[] — platforms × formats × counts
  │   · fee_usd + fee_rationale (cites comparables + budget_signal)
  │   · usage_rights[] + rationale
  │   · exclusivity (category + duration_days) + rationale
  │   · timeline[] (milestones with target_dates) + rationale
  │   · additional_compensation[] (gifted product / equity / etc.)
  │   · payment_terms (e.g. "50/50 NET-30")
  │   · exclusions[] (what's NOT included — pre-empts friction)
  │   · overall_rationale (top-level thesis)
  │  Written to commercial_proposal.llm_proposed + proposed_at.
  │  ────────── COMMERCIAL GATE ──────────
  │  Agent UI surfaces each field with LLM rationale.
  │  Agent reviews. Can edit any field; overrides captured in
  │  commercial_proposal.confirmed_overrides[].
  │  Agent clicks "Confirm" → sets:
  │   · commercial_proposal.confirmed_at
  │   · commercial_proposal.confirmed_by_agent_id
  │   · deal.proposal.commercial_confirmed_at
  │   · deal.proposal.commercial_confirmed_by_agent_id
  │   · deal.proposal.deliverables[] / fee_usd / usage_rights_granted /
  │     exclusivity / additional_compensation[] (canonical values)
  │  ────────── GATE PASSED ──────────
  │  If agent doesn't confirm, the pack stays in pre-render state:
  │   · export_artifacts[].status = "blocked_by_commercial_gate"
  │   · slides[] = []
  │   · agent can edit commercial fields freely; no version increment
  │
  ▼ STAGE D — Slide generation (3 Sonnet passes, prompt-cached)
  │  Pass 1: executive summary — 3-line thesis (what + outcome + why us)
  │  Pass 2: slides[] generation:
  │   · Forks talent_overview / audience_snapshot / recent_work /
  │     fit_angle slides from forked_from_prep_pack_id
  │   · Generates new proposal-specific slides:
  │     objectives_recap (lifts discovery_debrief.objectives_heard
  │     verbatim — "here's what we heard you say"); recommendation;
  │     deliverables (table from commercial_proposal); timeline;
  │     investment (fee + payment terms); usage_rights; exclusivity;
  │     exclusions; agency_process; next_steps_proposal
  │  Pass 3: speaker_notes per slide
  │  Each pass shares context via prompt-caching where supported.
  │
  ▼ STAGE E — Render artefacts
  │  Same renderer stack as discovery prep:
  │   · live HTML (slides[].live_body) via Jinja2 + agency branding
  │   · leave-behind HTML (live_body + leave_behind_extension)
  │   · PDFs via Puppeteer
  │   · speaker-notes.md via markdown writer
  │   · commercial-summary.md (the confirmed commercial proposal as
  │     a standalone reference for the agent)
  │   · PPT via slide skill (when wired; status: pending otherwise)
  │  Written to data/deals/{deal_id}/proposal_packs/v{N}.json +
  │  v{N}_artifacts/
  │
  ▼ Agent reviews v1; iterates via NL feedback → v2, v3, ...
  │
  ▼ Agent marks "ready to send" → sets:
     · deal.proposal.proposal_attachment_id = leave-behind PDF
     · deal.proposal.proposal_sent_at
     · deal.substage → proposal_sent
```

## Default slide structure

15 slides live mode; ~22-25 with leave-behind extensions. Slides 4-6 fork from the discovery prep pack (KPIs may refresh).

| # | Section | Slide type | Forked? | Live content |
|---|---|---|---|---|
| 1 | Title | title | New | Talent × Brand; proposal version + date; agent name |
| 2 | Executive summary | executive_summary | New | 3-line thesis: what we'll do + what it'll achieve + why this team |
| 3 | **Objectives recap** | objectives_recap | New | Lifts `discovery_debrief.objectives_heard` verbatim — confirms we heard the brand. Powerful trust signal. |
| 4 | Talent overview | talent_overview | Forked from prep | Headshot, niche, positioning |
| 5 | Audience snapshot | audience_snapshot | Forked from prep | KPI tiles (refreshed if >7d since prep) |
| 6 | Recent work | recent_work | Forked from prep | 2-3 case study tiles |
| 7 | Our recommendation | recommendation | New | The angle/concept for this campaign — synthesised from debrief + top pitch_angles |
| 8 | Deliverables | deliverables | New | Table: platform × format × count, with per-deliverable rationale callouts in leave-behind |
| 9 | Timeline | timeline | New | Table: milestone × target date |
| 10 | Investment | investment | New | Fee + payment terms (light rationale; heavier in leave-behind) |
| 11 | Usage rights | usage_rights | New | What's included (organic / whitelisting period / paid social / etc.) |
| 12 | Exclusivity | exclusivity | New | Category + duration |
| 13 | What's not included | exclusions | New | Explicit exclusions — reduces friction during execution |
| 14 | How we work | agency_process | New | 3-step process |
| 15 | Next steps | next_steps_proposal | New | What brand does to move forward (sign + return; intro to legal; PO process) |

**Forked slides** carry `forked_from_prep_slide_id` referencing the prep pack's slide_id. The agent can choose to regenerate forked slides if discovery context evolved (e.g. talent KPIs significantly updated since the discovery call).

## Commercial gate — detailed behaviour

Before gate passed:
- `commercial_proposal.llm_proposed` exists; `proposed_at` set
- `commercial_proposal.confirmed_at` ABSENT
- `slides[]` empty
- `export_artifacts[]` all `status: "blocked_by_commercial_gate"`
- Agent UI shows commercial review form with LLM rationale per field
- Agent can edit any field freely; no version increment for edits during this phase

When agent clicks "Confirm":
1. `commercial_proposal.confirmed_at` + `confirmed_by_agent_id` set
2. Any agent edits captured in `commercial_proposal.confirmed_overrides[]`
3. Values copy into `deal.proposal.*` (canonical commercial source-of-truth)
4. `deal.proposal.commercial_confirmed_at` + `commercial_confirmed_by_agent_id` set
5. Stage D fires automatically — slide generation begins
6. UI transitions from commercial-review to slide-review mode

After gate passed:
- Subsequent commercial edits = `agent_edits[]` entries with `edit_type: "commercial_override"`
- Each commercial override re-syncs the affected `deal.proposal.*` field
- A commercial override typically triggers a per-section regen for the affected slides (e.g. fee change → `target_sections: ["slides[investment]"]`)

## Negotiation tie-in

When the brand pushes back, the agent records the pushback in `deal.proposal.negotiation_log[]`:

```jsonc
{
  "at": "2026-04-28T14:00:00Z",
  "direction": "received_from_brand",
  "channel": "email",
  "summary": "Brand requested 90d whitelisting instead of 60d; fee unchanged.",
  "terms_changed": "whitelisting_period",
  "attachment_ids": ["att_brand_reply_email_xyz"],
  "proposal_pack_version": 1   // the version they pushed back on
}
```

Agent then triggers a `negotiation_response` regen. The new version's `generation`:

```jsonc
{
  "trigger": "negotiation_response",
  "negotiation_log_entry_ref": "2026-04-28T14:00:00Z",
  "regeneration_feedback": "Brand requested 90d whitelisting instead of 60d; fee unchanged.",
  "target_sections": ["commercial_proposal.usage_rights", "slides[usage_rights]"],
  ...
}
```

Bidirectional link: `negotiation_log[].proposal_pack_version` → proposal_pack version that received the pushback; new proposal_pack version's `generation.negotiation_log_entry_ref` → the log entry that triggered it.

## Storage layout

```
data/deals/{deal_id}/
  prep_packs/                    # Phase 4.5 (existing)
    v1.json, v1_artifacts/, ...
  proposal_packs/                # Phase 4.6 (NEW)
    v1.json
    v1_artifacts/
      proposal-live.html
      proposal-leave-behind.html
      proposal-live.pdf
      proposal-leave-behind.pdf
      speaker-notes.md
      commercial-summary.md
      proposal.pptx              # via slide skill
    v2.json
    v2_artifacts/...
  context_uploads/               # NEW — raw uploaded source files
    ctx_abc123_brand_brief_q2_2026.pdf
    ctx_def456_discovery_notes_apr18.docx
    ctx_ghi789_competitor_examples.pdf
```

All gitignored. Raw uploads retained for life of deal; purged on archive.

**File size caps (v0.1):** 25MB per file, 100MB total per deal. Bigger files require external storage link (use the `external_url` field on context_artefact instead of `stored_filepath`).

## Integration touchpoints

| Existing piece | How Phase 4.6 plugs in |
|---|---|
| **Phase 4.5 discovery prep** | `context_snapshot.forked_from_prep_pack_id` references the source prep pack version. Slides lift via `forked_from_prep_slide_id`. Briefing's `commercial_range` seeds the LLM's fee proposal. |
| **`deal.lead.discovery_debrief`** | Hybrid extraction output (Stage B) writes here. The proposal generation reads here (Stage C). Cross-version anchor — multiple proposal versions can share the same debrief. |
| **`deal.proposal.*`** | Canonical commercial source-of-truth. Confirmed values from `commercial_proposal.confirmed_overrides` write here on gate-pass. |
| **`deal.proposal.negotiation_log[]`** | Each entry has `proposal_pack_version` field. New `negotiation_response` regens have `generation.negotiation_log_entry_ref` pointing back. Bidirectional. |
| **Phase 0 agency branding** | Logo + colors + fonts auto-applied to renderer. Same single-source-of-truth pattern as Phase 4.5. |
| **Phase 1.5 brand_deals** | Comparable past deals seed commercial proposal rationale + recent_work slides. |
| **`data/pitch_angles.json`** | Top-scoring angles for this brand × niche seed the recommendation slide. |
| **Phase 4.7 contract pack** | Downstream artefact. The confirmed commercial values (`deal.proposal.deliverables`, `fee_usd`, `usage_rights_granted`, `exclusivity`, `additional_compensation`, payment terms) become merge fields in the contract template. The latest proposal pack's id is captured in `contract_pack.context_snapshot.proposal_pack_id_at_gen` for traceability. See `docs/contract_pack_workflow.md`. |
| **Brand legal entity proactive capture** | If `brand_industry_map.brands[].legal_entity` is absent for this brand AND no `brand_candidate.legal_entity_override` exists, the commercial gate surfaces a warning: "Brand legal entity not captured — required for contract draft. Add now or defer to contract stage?" Capturing here avoids late-stage friction in Phase 4.7 Stage A. Agent can upload W-9 / company registration; LLM extracts; agent confirms; writes to `brand_candidate.legal_entity_override` (or back to canonical `brand_industry_map.brands[].legal_entity` if the agent indicates this is the brand's standard entity, not a deal-specific override). |

## Failure handling

| Failure | Behaviour |
|---|---|
| File parsing fails (corrupt PDF, unsupported format) | Surface to agent: "Couldn't parse {filename} — try re-saving as PDF or pasting text directly." File still uploads + retained; just no `parsed_text` populated. Agent can manually paste content as text artefact instead. |
| File exceeds size cap | Reject with explicit error pointing to the external-URL alternative. |
| Discovery debrief extraction has all `confidence: low` | Surface warning: "Debrief signal is weak — proposal will be heavily LLM-inferred. Consider adding more notes before proceeding." Agent can override and proceed anyway. |
| Agent tries to trigger Stage D (slide render) before commercial gate | Reject with explicit error: "Confirm pricing + deliverables before slides can render." |
| LLM proposes fee outside reasonable range (e.g. <50% or >200% of briefing's commercial_range) | Flag in UI with rationale shown. Agent can override and proceed. No hard block — the agent's judgement overrides. |
| Discovery prep pack not present (rare — e.g. repeat brand skipping discovery) | `forked_from_prep_pack_id` is null. Talent slides generated fresh from talent profile + brand_deals; no fork. UI flags "No discovery prep pack — proposal generated from scratch." |
| Slide skill unavailable | Same as discovery: HTML + PDF render via fallback; PPT marked `status: pending`. |
| Agent regenerates with conflicting commercial overrides | Commercial overrides applied last wins for `deal.proposal.*`. Each override individually captured in `agent_edits[]`. |
| Concurrent regen + edit | Same last-write-wins as Phase 4.5. |

## Cost profile

Per-pack: ~4-5 Sonnet passes (artefact summary + debrief extraction + commercial proposal + executive summary + slides + speaker notes), heavily cached. ~25-35k input tokens (uploads + debrief + comparables) + ~12-15k output tokens. Estimated **$0.30-0.60 per generation**. Iteration cost scales with negotiation rounds — typical deal: 2-4 versions.

## v0.1 explicit non-goals

- **Auto-fire on substage transition.** Higher stakes than discovery prep — kept agent-initiated.
- **In-house audio transcription.** v2 only — external transcript service URL references.
- **Image / video OCR.** v2.
- **Auto-send proposal to brand.** Always agent-initiated; system never emails the proposal directly.
- **Brand-side edit mode.** Brand cannot edit the proposal directly; pushback flows via `negotiation_log[]`.
- **Multi-currency invoicing.** Proposals can quote in non-USD via `fee_currency_original` but `deal.proposal.fee_usd` is always USD-normalised for analytics.

## Open questions for v0.2

1. **Proposal templates per industry** — activewear vs. CPG vs. SaaS proposals have different conventions. Promoting the default slide structure to `data/proposal_templates.json` (per `pitch_templates.json` precedent) lets agencies tune per-industry. v0.2.
2. **Counter-offer detection** — when brand replies to a proposal, can we auto-classify (counter / accept / reject / clarification) the same way Phase 3b classifies cold replies? Would speed up `negotiation_log[]` capture. v0.2.
3. **Win/loss feedback into the LLM's pricing model** — track LLM-proposed-fee vs. agent-confirmed-fee vs. final-paid-fee. Train a per-agency calibration so future proposals are systematically less-over or less-under priced. v0.2.
4. **Brand-side approval-tracking sub-spec** — if the brand has a multi-stakeholder approval workflow (legal → finance → CMO), surface that in the proposal pack so the agent can track per-stakeholder status. v0.2.
5. **Co-presentation mode** — when agent walks brand through the proposal in a follow-up call, real-time annotation / "what changed" highlighting between versions would help. v0.2.
6. **Auto-generate the contract draft from the confirmed commercial proposal** — Phase 4 CONTRACT stage's `draft_contract_attachment_id` could be auto-seeded from this pack's confirmed values. v0.2.
7. **Per-deliverable concept slides** — for larger campaigns, expand the single `deliverables` slide into one slide per deliverable with concept/treatment description. v0.2.
