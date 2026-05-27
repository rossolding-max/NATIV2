# Discovery Call Prep Workflow (Phase 4.5)

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the discovery-call prep pipeline — auto-drafts agenda + briefing notes + slide deck when a Phase 4 LEAD-stage deal transitions to `substage = initial_call_scheduled`. Versioned, iteratively refinable via natural-language feedback, ready by call time minus 24h.

**Pairs with:**
- `schemas/discovery_prep_pack.schema.json` — the data contract.
- `docs/deal_lifecycle_workflow.md` (Phase 4) — this workflow fires inside LEAD stage; outputs reference deal context.
- `docs/agency_setup_workflow.md` (Phase 0 Step 1.5) — agency branding (logo + colors + fonts) is required input.
- `docs/vendor_roadmap.md` — Exa for external research; slide skill (provided separately) for HTML/PDF/PPT rendering.

## Goal

Walk the agent into a discovery call fully briefed in 5 minutes of reading instead of 90 minutes of research, with a slide deck the brand will remember. Three locked-in design decisions:

1. **Agent solo on the call** — talent does not attend discovery calls. Briefing notes are internal cheat-sheet; slides position the talent to the brand.
2. **One deck source, two output variants** — live screen-share (sparse) + leave-behind (dense) + separate speaker notes. Generated from a single structured `slides[]` JSON.
3. **LLM auto-drafts everything end-to-end** — agenda, briefing, slides. Agent reviews + edits. Iterative refinement via natural-language feedback creates new versions; old versions retained as history.

Ultimate objective: the agent never has to do prep research from a blank page. The system delivers a complete, citable, on-brand pack; the agent's job is to refine and own it.

## When it fires

| Trigger | Behaviour |
|---|---|
| Deal substage → `initial_call_scheduled` | Auto-generation fires. v1 prep pack ready within ~5 minutes. Agent is notified in their daily summary 24h before the call. |
| Agent requests regenerate (full pack) | New version v(N+1) generated with agent's `regeneration_feedback` as additional prompt input. Parent version retained. |
| Agent requests regenerate (specific sections or slides) | Same as above but `generation.target_sections` limits what gets rebuilt. Other sections carry forward from parent. |
| Upstream data changes (talent KPIs / brand context / new contact info) | **V1 stays locked.** No auto-regen. Agent sees a soft drift indicator ("Talent KPIs updated since prep pack generated — regenerate?") but the decision is theirs. |
| Agent directly edits a slide via the slide skill's editor | Logged in `agent_edits[]`. No new version. The current version's slide content updates in place. |

## The 3 outputs

### Agenda
Single-page markdown rendered from `agenda.sections[]`. Default 45-minute structure with 6 fixed sections, LLM-customised per deal (durations rebalanced; talking points tailored):

| # | Section | Default duration | Purpose |
|---|---|---|---|
| 1 | **Introductions** | 2 min | Rapport, confirm logistics, set expectations for the call |
| 2 | **Brand overview** | 5 min | Walk through what we understand about the brand from our research; confirm + correct. If a formal brief was already received, this section is lighter (5 → 3 min) and rolls into Objectives. |
| 3 | **Talent overview** | 8 min | Talent positioning, audience snapshot, recent work — the strongest 2-3 case studies for context |
| 4 | **Objectives** | 15 min | What the brand is trying to achieve, current friction, why now. Discovery moment — the agent listens. Internally this section captures the brand's situation, pain, impact, and critical event (SPICED framework adapted from B2B sales discovery — but the framework's terms are **never** surfaced in any client-facing artefact). Briefing notes carry the agent's structured questions for this section. |
| 5 | **Opportunities** | 12 min | Where we see fit — float 1-2 angle ideas tailored to what was just heard in Objectives. Open-ended discussion of scope, timing, budget signals. |
| 6 | **Next steps** | 3 min | Proposal timeline, info we still need, who else from the brand needs to weigh in |

**Per-deal LLM customisation:**
- Brief already received in writing? → trim Brand overview, expand Objectives
- Brand asked specific questions in reply? → surface them as opening of Objectives section
- High commercial range deal → expand Next steps to cover decision process + stakeholder mapping
- Repeat brand (have done a deal before) → trim Brand overview to "what's changed since last time", trim Talent overview, expand Opportunities

Each section in `agenda.sections[]` has `title` + `duration_min` + `purpose` + `talking_points[]`. The Objectives section's talking_points are framed as questions the agent will ask (e.g. "What does success look like for this campaign in 6 months?", "What's not working with current creator partnerships?", "Why now — what's the trigger to act?") — not as topics the agent presents.

### Briefing notes
Multi-section markdown, internal/agent-only. Renders from `briefing_notes` structured fields:

| Section | Source data |
|---|---|
| Deal summary | Originating pitch + reply text from Phase 3b enrollment |
| About the brand | Phase 2 brand_candidates + Exa external research |
| About the contact | Phase 3a brand_contact + pitch_history |
| About the talent for this call | Phase 1 talent profile + Phase 1.5 brand_deals filtered to similar industry/scope |
| Fit hypothesis | LLM synthesis from top-scoring `pitch_angles` for this brand × niche |
| Likely objections + responses | Patterns from past `objection`-classified outcomes in `scripts/analyze_outreach.py` |
| Red flags | Cross-check talent's `red_lines` against brand data |
| Questions to ask THEM | LLM-generated discovery questions for the **Objectives** agenda section — situation, pain, impact, critical-event probes (using plain language, not SPICED terms) |
| Questions FROM them + prepared answers | Anticipated buyer questions with prepared answers |
| **Commercial range** | Computed from comparable past `brand_deals` fees × similar deliverable scope. Surface in briefing **only** — not shown to brand on call unless they ask. |

The briefing notes are agent-only, so they CAN reference the SPICED framework explicitly for the agent's mental model — but no rendered slide or agenda artefact ever uses those terms.

Every non-obvious claim carries provenance per honesty-floor: source + as_of.

### Slide deck — structured JSON → 3 rendered artefacts

Source: `slides[]` array of structured slide objects. Each slide has:
- `type` — drives layout template (title / talent_overview / audience_snapshot / case_study / fit_angle / process / next_steps / custom)
- `live_body` — sparse content (headline, subheadline, body_text, bullets, kpi_tiles, image_refs, callout)
- `leave_behind_extension` — additional written context (expanded_body, supporting_data, footnotes)
- `speaker_notes` — what the agent says
- `sources[]` — citations for any factual claim

**Default deck structure (10 slides live mode; ~15 with leave-behind extensions enabled) — ordered to match the agenda flow:**

| # | Agenda section | Type | Live content | Leave-behind extension |
|---|---|---|---|---|
| 1 | Introductions | title | Talent name × Brand name; date; agent name | Agency tagline footer |
| 2 | Brand overview | brand_observation | "What we see at [Brand]" — 3-4 observations from research with sourced callout | Detailed observation block + recent campaign context |
| 3 | Talent overview | talent_overview | Headshot, niche, positioning statement | Bio paragraph + content philosophy |
| 4 | Talent overview | audience_snapshot | 4-6 KPI tiles (followers, engagement, demo splits) — sourced | Methodology note + audience-research provenance |
| 5 | Talent overview | recent_work | 2-3 case study tiles auto-pulled from brand_deals | Outcome paragraphs with KPI deltas |
| 6 | **Objectives** | context | Single prompt slide: "Your objectives" with 3-4 discussion prompts (e.g. "What does success look like?", "What's the trigger to act now?") — the agent listens, doesn't present. Slide is wallpaper for the conversation. | (Empty — this section is conversation, not content. Speaker notes carry the agent's question playbook.) |
| 7 | Opportunities | fit_angle | Top-1 angle headline + 2-3 supporting bullets | Full angle rationale + supporting data |
| 8 | Opportunities | proof_point | Best comparable case study with the headline KPI | Full case study writeup |
| 9 | Opportunities | process | How we work — 3-step flow | Detailed process + timelines |
| 10 | Next steps | next_steps | What we need to build a proposal | Sample proposal timeline |

The `context` slide type (slide 6) acts as the Objectives section's visual anchor. The agent doesn't present this slide — they leave it up while the brand talks, using the speaker_notes as their structured question playbook. Slide 7's `fit_angle` content is the agent's response to what they heard in Objectives — so this slide is often the one most heavily edited via natural-language feedback after the agent sees v1.

**Rendered exports — v0.1 ships markdown only; visual slide rendering deferred to v2:**

| Artefact | v0.1 ships? | Generated from | Renderer | Use |
|---|---|---|---|---|
| `briefing-notes.md` | ✅ | `briefing_notes` block | Markdown writer | Agent reads pre-call (PRIMARY v0.1 deliverable) |
| `agenda.md` | ✅ | `agenda` block | Markdown writer | Agent reference during the call |
| `speaker-notes.md` | ✅ | `slides[].speaker_notes` paired with `title` | Markdown writer | Second-screen reference for the agent — full per-slide structured content rendered as markdown sections |
| `slides.md` | ✅ | `slides[].live_body + .leave_behind_extension + .sources[]` | Markdown writer | All slide content concatenated as a single markdown document — agent reads through pre-call |
| `deck-live.html` | ❌ v2 (V2-PACK-01) | `slides[].live_body` | Jinja2 + agency branding | Screen-shared on the call — v2 only |
| `deck-leave-behind.html` | ❌ v2 (V2-PACK-01) | `slides[].live_body + leave_behind_extension` | Jinja2 + agency branding | Post-call leave-behind — v2 only |
| `deck-live.pdf` | ❌ v2 (V2-PACK-01) | HTML via Playwright | Playwright | Read-only fallback — v2 only |
| `deck-leave-behind.pdf` | ❌ v2 (V2-PACK-01) | HTML via Playwright | Playwright | Sent to brand — v2 only |
| `deck.pptx` | ❌ v2 (V2-PACK-01) | Via slide skill | Slide skill (user-provided) | Editable for buyer to share internally — v2 only |

**Why prep pack ships markdown only in v0.1 (per `docs/v2_deferred_requirements.md` V2-PACK-01):**

The prep pack is INTERNAL — for the agent's pre-call prep, NOT shown to the brand. Markdown briefing notes + agenda + speaker notes + slides content are sufficient for in-call agent reference. The visual slide rendering pipeline (Jinja2 + Playwright headless Chromium + branding application + PPTX export) is heavy investment that first pays off in M12 / Phase 4.6 where the proposal pack IS brand-facing.

The `discovery_prep_pack.slides[]` schema is unchanged: all slide content (live_body / leave_behind_extension / speaker_notes / sources) is still generated by the writer subagent and persists in the pack record. v2 just adds the renderer pipeline that turns slide content into HTML / PDF / PPTX artefacts. No schema migration needed at v2 cutover.

## Generation pipeline

```
Trigger: deal.substage transitions to initial_call_scheduled
  │
  ▼ Agent (optional): provides `pre_generation_guidance` text
  │  e.g. "Lead with Lululemon case study; brand told us in reply
  │   they want performance not lifestyle."
  │
  ▼ Gather context (deterministic, no LLM)
  │  - Deal record + originating_enrollment + reply text
  │  - Talent profile (Phase 1) + brand_deals (Phase 1.5)
  │  - Brand candidate + qualification rationale (Phase 2)
  │  - Brand contact + pitch_history + signals (Phase 3a)
  │  - Top-scored pitch_angles for this brand × niche
  │  - agency_profile.branding (logo + colors + fonts)
  │
  ▼ External research pass (Exa)
  │  - 3-5 targeted queries: brand recent campaigns, brand news,
  │    contact background, competitor landscape
  │  - Each query result summarised by Sonnet; URLs retained
  │    for citation
  │  - Snapshot stored in `context_snapshot.external_research`
  │
  ▼ LLM Pass 1: briefing_notes (Claude Sonnet)
  │  Input: gathered context + external research + pre_generation_guidance
  │  Output: structured briefing_notes object
  │  Prompt-caching: all context cached for reuse by passes 2 + 3
  │
  ▼ LLM Pass 2: agenda (Claude Sonnet)
  │  Input: cached context + briefing_notes output
  │  Output: structured agenda object (sections[] with durations)
  │
  ▼ LLM Pass 3: slides (Claude Sonnet)
  │  Input: cached context + briefing_notes + agenda
  │  Output: structured slides[] array (10-12 slides typical)
  │
  ▼ Validate against schemas/discovery_prep_pack.schema.json
  │
  ▼ Render artefacts
  │  - HTML decks via Jinja2 with agency_profile.branding
  │  - PDF via Puppeteer (headless Chromium)
  │  - Speaker notes + briefing + agenda via markdown writer
  │  - PPT via slide skill (when wired; otherwise `status: pending`)
  │
  ▼ Write to data/deals/{deal_id}/prep_packs/v{N}.json
  │  + data/deals/{deal_id}/prep_packs/v{N}_artifacts/
  │
  ▼ Update deal: append to lead.discovery_prep_pack_ids[],
  │  set lead.latest_prep_pack_id
  │
  ▼ Surface in agent's morning summary 24h before call:
     "Prep pack v1 ready for [brand] call on [date] at [time]"
```

## The natural-language feedback loop

After v1 is generated, the agent can iterate:

```
Agent reviews v1 → drops natural-language feedback into the UI:

  "Slide 4 audience claim feels overstated — tone it down and add
   the as-of date. Drop the sustainability angle entirely, brand
   told me on the intro email they're focused on performance not
   values. Beef up the commercial range — I think we're underselling
   for this scope."

→ Orchestrator captures as `generation.regeneration_feedback`
→ LLM receives: original context + v1 full pack + feedback text
→ Pass 1 (briefing) regenerates with feedback applied
→ Pass 2 + 3 regenerate downstream sections
→ v2 written with parent_version: 1
→ v1.is_latest flips to false; v2.is_latest = true
→ Old versions stay queryable from lead.discovery_prep_pack_ids[]
```

**Section-targeted regeneration:** the agent can target sub-sections instead of full rebuild:
- "Regenerate just the objections section" → `generation.target_sections: ["briefing.likely_objections"]`
- "Redo slides 4 and 7" → `generation.target_sections: ["slides[3]", "slides[6]"]`

Sections not in `target_sections` carry forward from parent_version unchanged. Faster + cheaper for small refinements.

## Direct slide editing

The slide skill produces editable HTML. The agent can:
1. **Edit slide content directly** — type into the slide in-place; saves update the current version's `slides[N].live_body` / `leave_behind_extension` and append an entry to `agent_edits[]`. No new version.
2. **Provide natural-language feedback per slide** — "make this punchier", "use a darker accent color", "swap to a 2-column layout". Triggers a per-slide LLM regen → produces v(N+1) with `trigger: agent_per_slide_regenerate` and `target_sections: ["slides[X]"]`.

The slide skill is responsible for exposing both interaction modes in its UI. The orchestrator-side contract:

```jsonc
// Slide skill input
{
  "slides": [...],                  // from prep_pack
  "branding": {...},                // from agency_profile.branding
  "mode": "live" | "leave_behind",
  "editable": true                  // agent can edit directly
}

// Slide skill output
{
  "html_path": "...",               // editable HTML deck
  "pdf_path": "...",                // read-only PDF
  "pptx_path": "...",               // editable PPT
  "on_edit": "callback_url",        // slide skill POSTs here on agent edit
  "on_feedback": "callback_url"     // slide skill POSTs feedback for LLM regen
}
```

Until the skill is wired, v0.1 fallback:
- HTML via Jinja2 template + agency branding
- PDF via Puppeteer
- PPT marked `status: pending` in `export_artifacts[]`
- Direct edit + natural-language feedback both surface as "pending slide-skill integration" with the underlying slides[] still editable via the orchestrator API.

## Storage layout

```
data/deals/{deal_id}/
  prep_packs/
    v1.json                          # full prep pack data
    v1_artifacts/
      deck-live.html
      deck-leave-behind.html
      deck-live.pdf
      deck-leave-behind.pdf
      speaker-notes.md
      briefing-notes.md
      agenda.md
      deck.pptx                      # via slide skill, when wired
    v2.json                          # after first regeneration
    v2_artifacts/
      ...
    v3.json
    ...
```

All gitignored — commercial data + research summaries + agency branded artefacts.

## Integration touchpoints

| Existing piece | How Phase 4.5 plugs in |
|---|---|
| **Phase 0 agency_profile.branding** | Logo + colors + fonts auto-applied to every slide. Rebrand in Phase 0 → propagates to all future prep packs on next render. |
| **Phase 1 talent profile** | Source for talent overview, audience snapshot, positioning. `context_snapshot.talent_profile_updated_at` records the version consumed. |
| **Phase 1.5 brand_deals** | Source for recent_work + proof_point + case_study slides. `context_snapshot.comparable_brand_deal_ids` records the FKs cited. |
| **Phase 2 brand_candidates** | Source for "about the brand" section. Qualification rationale informs the fit hypothesis. |
| **Phase 3a brand_contacts** | Source for "about the contact" section. `pitch_history` mined for engagement signals. |
| **Phase 3b pitch_enrollments** | Originating reply text is anchor citation — quoted in briefing summary, used to seed angle selection. |
| **Phase 3b outreach analyzer** | Past `objection`-classified outcomes mined for "likely objections" section. |
| **`data/pitch_angles.json`** | Top-scoring angles for this brand × niche feed `fit_angle` slide + briefing fit hypothesis. |
| **Phase 4 deal record** | `lead.discovery_prep_pack_ids[]` + `lead.latest_prep_pack_id` are FK references. `deal.lead.discovery_call_notes` post-call can reference the prep pack version that was used. |
| **Phase 4.6 proposal pack** | The downstream artefact. Proposal pack's `context_snapshot.forked_from_prep_pack_id` references this prep pack's version; its `slides[*].forked_from_prep_slide_id` references individual slides that carry over. Briefing's `commercial_range` seeds the LLM's fee proposal in the proposal pack's Stage C. The Objectives recap slide in the proposal lifts `deal.lead.discovery_debrief.objectives_heard` — closes the loop: brand sees we heard what they said. See `docs/proposal_pack_workflow.md`. |

## Failure handling

| Failure | Behaviour |
|---|---|
| Exa API down | Generation continues without external_research. `context_snapshot.external_research.provider: "none"`. Briefing flags "External research unavailable — refresh later for richer brand context." |
| LLM pass fails (rate limit / timeout) | Retry with exponential backoff (3 attempts). On final failure, write a partial prep pack with the passes that succeeded + a `generation_error` field; surface to agent. |
| Slide skill unavailable | HTML/PDF still render via Jinja2 + Puppeteer. PPT artefact stays `status: pending` until skill is wired. Agent can still review + edit the HTML deck. |
| Comparable brand_deals empty (new talent, no history) | LLM skips case_study + proof_point slides; deck is shorter. Commercial range falls back to industry-standard ranges with a clear "no historical data — use as orientation only" caveat. |
| Talent profile has placeholder KPIs (e.g. `value: null, source: "pending"`) | Slides 4 / 8 / proof_point skip those KPIs. Briefing flags "Talent KPI capture incomplete — refresh from Phase 1 onboarding before the call." |
| Agent regenerates many times rapidly | No throttling in v0.1 (single-agent). v2: rate-limit per deal (e.g. max 10 regens / 24h) to control cost. |
| Direct edit conflicts with concurrent regen | Last-write-wins on the current version. If a regen triggers while agent is editing, the regen creates a new version (v+1) with parent_version pointing at pre-edit state; agent's edits are preserved in v(N).agent_edits[] but don't carry into v(N+1) automatically. |

## v0.1 explicit non-goals

- **Auto-regenerate on upstream data refresh.** Decided: v1 stays locked unless agent asks. Drift detection is informational only.
- **Closed-loop quality improvement.** v0.1 doesn't learn from agent edits/feedback to improve future generations across deals. v2 could pattern-mine agent feedback to refine prompts.
- **Multi-talent decks.** v0.1 = one talent per deal per prep pack. Multi-talent campaigns (rare) need v2.
- **Real-time co-presentation.** Slides are static artefacts — no live audience polling, no real-time annotation. v2.
- **Translation / localization.** v0.1 = English only. v2 for international agencies.

## Open questions for v0.2

1. **Cost budget per deal** — 3-pass Sonnet generation + Exa queries + iterative regens can run ~$1-3 per prep pack. At scale (50 active deals × 3 regens each = 150 generations/month), this is ~$150-450/mo. Worth a per-deal cost cap surfaced to the agent.
2. **Prompt templates as data** — currently the LLM prompts for each pass are hardcoded in `scripts/generate_discovery_prep.py`. Promoting them to `data/prep_prompts.json` lets agencies tune the system prompt per their voice without code changes (parallel to `data/pitch_angles.json`).
3. **Calendar integration** — generation could fire on calendar-event-scheduled rather than substage change, syncing with Google Calendar / Outlook for the agent. v2.
4. **Auto-update post-call** — after the call, `deal.lead.discovery_call_notes` captures what was discussed. Could trigger a "summary of what was learned + what changed" note that feeds the PROPOSAL stage. v2.
5. **Slide A/B testing** — agencies could generate 2 variants of slide 7 (the fit_angle) and pick the stronger one. v2.
6. **Branding override per deal** — for co-branded campaigns or white-label work, override agency branding with a deal-specific brand kit. v2.
7. **Speaker notes audio rehearsal** — TTS the speaker notes so the agent can listen on a commute. v2.
