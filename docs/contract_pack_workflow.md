# Contract Pack Workflow (Phase 4.7)

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the contract pack pipeline — the artefact for Phase 4 CONTRACT stage. Auto-drafts the contract from the talent's contract template + the deal's confirmed proposal commercials + agent-uploaded brand legal info. Hard legal review gate before render. Output: markdown source (canonical) + Word .docx (editable) + PDF (read-only).

**Pairs with:**
- `schemas/contract_pack.schema.json` — the data contract.
- `schemas/talent.schema.json` — `talent.contract_template` block is the template source (captured in Phase 1 onboarding).
- `docs/proposal_pack_workflow.md` (Phase 4.6) — upstream artefact. Confirmed commercials (`deal.proposal.*`) seed contract merge fields. Proposal pack id captured in context snapshot.
- `docs/deal_lifecycle_workflow.md` (Phase 4) — CONTRACT substage fires this. Existing `deal.contract.draft_contract_attachment_id` + `contract_attachment_id` auto-populate from latest render.
- `docs/onboarding_workflow.md` (Phase 1) — talent's `contract_template` captured during onboarding.
- `docs/agency_setup_workflow.md` (Phase 0) — agency provides "starter templates" in `data/contract_template_starters/` that talent onboarding can copy from.
- `docs/vendor_roadmap.md` — python-docx + Puppeteer/pandoc for rendering (no new vendors); Phase 4 v2 e-sign API integration (DocuSign/PandaDoc/HelloSign).

## Goal

Take everything we know about the deal — confirmed commercials, talent's standard terms, the brand we're contracting with — and produce a draft contract that's 80% complete on first generation. Legal review tightens the remaining 20%. Locked-in design decisions:

1. **Template lives per-talent** (Phase 1 onboarding). Captures talent-specific clauses (moral, IP, dietary red lines) plus the agency's base. Inheritance happens at onboarding time — agency starter copied + edited.
2. **Markdown with merge fields as source-of-truth.** `{{merge_field}}` for deterministic substitution; `{{#if clause_id}}...{{/if}}` for conditional clauses; `{{narrative_*}}` for LLM-drafted bounded sections. Git-versionable; LLM-friendly; renders to Word + PDF.
3. **Hard legal review gate.** Generation produces a draft with merge values + clause decisions + narratives. Word + PDF artefacts cannot render until the gate is passed. Re-edits reset the gate (re-approval required) — strict but contract stakes warrant it.
4. **LLM scope: merge + narrative + conditional clauses; NOT full clause rewriting.** Predictable. Higher leverage than pure merge substitution; lower legal risk than free rewriting.

## When it fires

| Trigger | Behaviour |
|---|---|
| Agent clicks "Draft contract" on a deal in `contract_drafting` substage | v1 generation. Higher-stakes than discovery prep — agent-initiated, no auto-fire on substage transition. |
| Agent requests full regenerate | New v(N+1) with `regeneration_feedback`. Parent retained. |
| Agent requests section/clause regenerate | Same with `target_sections`. Untargeted carry from parent. |
| Brand sends redlined version | Agent uploads as `brand_redline` context_artefact + triggers `brand_redline_response` regen targeting the redlined sections. |
| Direct edit via UI | Logged in `agent_edits[]`. Resets `legal_review.approved_at` (re-approval required) unless agent flags `trivial_edit_override`. |
| Amendment post-execution | `trigger: amendment_request`. Writes to `deal.contract.amendment_log[]` rather than replacing the executed contract. |

## The 7-stage pipeline

```
Trigger: agent clicks "Draft contract" (substage = contract_drafting)
  │
  ▼ A. Context augmentation
  │    Agent uploads files via UI:
  │     · brand legal info (W-9, company registration, etc.)
  │     · brand-requested clauses (NDA, special IP terms)
  │     · prior contracts with this brand (for convention matching)
  │     · brand redline (if v(N+1) regen)
  │    Files parsed (pypdf/python-docx) + LLM-summarised.
  │    `llm_extracted_signals` for brand_legal_info pulls
  │    legal_name + registered_address + tax_id + signatory.
  │    Agent reviews summaries + tags relevance.
  │
  ▼ B. Merge field extraction & validation
  │    For each entry in talent.contract_template.merge_field_definitions[]:
  │     · Extract from declared source (e.g. talent.billing_entity.legal_name,
  │       deal.proposal.fee_usd, agency_profile.name)
  │     · Tag confidence (high=deterministic, medium=LLM-inferred with strong
  │       signal, low=LLM guess, missing=no value)
  │     · Flag needs_review for low/missing on required fields
  │    Critical fields (legal names, addresses, fees, dates) MUST be high
  │    confidence — anything less surfaces as blocking_issue.
  │
  ▼ C. Conditional clause evaluation
  │    For each entry in talent.contract_template.clause_applicability_rules[]:
  │     · If default_decision = include / exclude → applied directly
  │     · If llm_decide → LLM evaluates condition against full context
  │       and decides + records applicability_rationale
  │    Examples:
  │     · exclusivity → include if deal.proposal.exclusivity.duration_days > 0
  │     · gdpr → include if brand_legal_entity.country in EU member states
  │     · ip_assignment → include if deal.proposal.additional_compensation
  │       contains co_created_product
  │     · paid_social_addendum → include if deal.proposal.usage_rights
  │       contains any "paid_social_*"
  │     · moral_clause_strict → include from talent template defaults if
  │       talent has elevated risk concerns
  │    Each decision logged with decided_by (template_default/llm/agent).
  │
  ▼ D. Narrative drafting
  │    For each entry in talent.contract_template.narrative_placeholders[]:
  │     · LLM drafts content drawing from declared context paths
  │     · Tone guidance applied (e.g. "formal legal prose, no marketing
  │       language")
  │     · Word-count cap enforced (soft — exceeding flags for review)
  │     · Sources logged (e.g. ['deal.proposal.deliverables[0..2]',
  │       'discovery_debrief.objectives_heard[0]'])
  │    Bounded creativity — templated structure, LLM fills declared blanks.
  │
  ▼ E. Compose
  │    Template markdown_source + merge values + clause decisions + narratives
  │    → composed_markdown.
  │    Conditional blocks: `{{#if clause_id}}body{{/if}}` →
  │     - included: body kept verbatim
  │     - excluded: block stripped entirely
  │    Merge fields: `{{field}}` → substituted value
  │    Narrative placeholders: `{{narrative_*}}` → LLM-drafted content
  │
  ▼ F. LEGAL REVIEW GATE (HARD)
  │    Agent (or talent.contract_template.legal_reviewer_id if set) reviews:
  │     · Every merge_field_value with confidence + source (low-conf flagged)
  │     · Every clause decision with applicability_rationale
  │     · Every narrative section with sources
  │     · Full composed_markdown
  │    Agent can edit anything. Each edit logged in agent_edits[].
  │    blocking_issues[] auto-populated from low-confidence merge fields,
  │    missing required values, agent-flagged sections.
  │    Gate can only pass when blocking_issues is empty.
  │    On approval: legal_review.approved_at + approved_by_agent_id set.
  │    ────────── WORD + PDF ARTEFACTS CANNOT RENDER UNTIL APPROVED ──────────
  │
  ▼ G. Render
  │    Composed markdown:
  │     · contract.md — markdown writer (canonical source-of-truth)
  │     · contract.docx — python-docx (editable for agent/legal)
  │     · contract.pdf — Puppeteer headless Chromium OR pandoc
  │    All in data/deals/{deal_id}/contract_packs/v{N}_artifacts/
  │    On render: deal.contract.draft_contract_attachment_id auto-set to
  │    contract.pdf (canonical reference).
  │
  ▼ Agent sends to brand + talent:
     · deal.contract.sent_to_brand_for_review_at + _to_talent_for_review_at
     · v0.1 manual: email PDF/Word; capture signed PDF when returned
     · v2: DocuSign/PandaDoc/HelloSign auto-route + auto-populate signed_at
```

## Template structure

`talent.contract_template.markdown_source` typical layout:

```markdown
# Influencer Marketing Agreement

**Effective Date:** {{effective_date}}

## Parties

**Agency:** {{agency_name}}, {{agency_address}}, acting on behalf of
**Talent:** {{talent_legal_name}}, {{talent_billing_address}} ("Talent")

**Brand:** {{brand_legal_name}}, a {{brand_entity_type}} with registered
address at {{brand_registered_address}} ("Brand")

## 1. Scope of Work

{{narrative_scope_of_work}}

## 2. Deliverables

{{deliverables_table}}

## 3. Timeline

{{timeline_table}}

## 4. Fees and Payment

Total fee: {{fee_usd_formatted}}, payable on the following terms:
{{payment_terms}}

## 5. Usage Rights

The Brand is granted the following rights to use the Content:
{{usage_rights_list}}

{{#if paid_social_usage}}
### 5.1 Paid Social Amplification
{{narrative_paid_social_terms}}
{{/if}}

## 6. Exclusivity

{{#if exclusivity}}
Talent agrees not to create paid content for any direct competitor in the
{{exclusivity_category}} category for a period of {{exclusivity_duration_days}}
days following the final delivery date.
{{/if}}

## 7. Approval Process

{{narrative_approval_process}}

## 8. Content Ownership and IP

{{#if ip_assignment}}
{{narrative_ip_assignment}}
{{/if}}
{{#if !ip_assignment}}
Talent retains all intellectual property rights to the Content. Brand
receives a license to use the Content as described in Section 5.
{{/if}}

## 9. Confidentiality

Both parties agree to maintain confidentiality of all non-public
information shared during the term of this Agreement.

## 10. Termination

[Standard termination clause — agency default]

{{#if gdpr}}
## 11. Data Protection (GDPR)

{{narrative_gdpr_addendum}}
{{/if}}

## {{section_n}}. Governing Law

This Agreement is governed by the laws of {{governing_law}}, with
exclusive jurisdiction in {{jurisdiction}}.

## Signatures

Talent: ____________________  Date: __________
{{talent_signatory_name}}, {{talent_signatory_title}}

Brand: ____________________  Date: __________
{{brand_signatory_name}}, {{brand_signatory_title}}
```

The example uses ~20 merge fields, 4 conditional blocks (`paid_social_usage`, `exclusivity`, `ip_assignment` + its inverse, `gdpr`), 4 narrative placeholders (`scope_of_work`, `paid_social_terms`, `approval_process`, `ip_assignment`, `gdpr_addendum`).

## Hard legal review gate — detailed behaviour

**Before gate passed:**
- `legal_review.approved_at` ABSENT
- `legal_review.blocking_issues[]` may be non-empty (auto-populated from low-confidence merge fields + missing required values)
- `export_artifacts[]` all `status: "blocked_by_legal_gate"` for docx/pdf
- `composed_markdown` IS populated (agent needs to see the full draft to review)
- Agent UI shows commercial-review-style form: each merge field with confidence + source; each clause decision with rationale; each narrative section
- Agent can edit anything freely; edits log to `agent_edits[]` but don't increment version

**Gate pass:**
1. All `blocking_issues[]` must be resolved (cleared or marked `resolved_at`)
2. Reviewer clicks "Approve" → `legal_review.approved_at` + `approved_by_agent_id` set
3. Stage G fires: contract.docx + contract.pdf render
4. `deal.contract.draft_contract_attachment_id` auto-set to the PDF
5. Agent can now send to brand + talent (manual v0.1; v2 e-sign integration)

**Post-approval edits:**
- Any agent_edit with `resets_legal_gate: true` (default) pushes current approval to `legal_review.previous_approvals[]` and clears `approved_at` — re-approval required
- Trivial edits (typos, whitespace, formatting): agent can mark `trivial_edit_override: true` to skip the reset. Agent decides at edit time; logged in audit trail.
- Re-approvals stack in `previous_approvals[]` with `reset_reason` so the audit trail shows the full review-edit-review cycle

**Reviewer identity:**
- Defaults to `talent.contract_template.legal_reviewer_id` if set
- Otherwise defaults to `deal.assigned_agent_id`
- The legal_review.reviewer_id field locks who can approve — only that identity can pass the gate

## Storage layout

```
data/deals/{deal_id}/
  prep_packs/                    # Phase 4.5
  proposal_packs/                # Phase 4.6
  context_uploads/               # Phase 4.6 + 4.7 shared upload folder
    ctx_brand_w9.pdf
    ctx_brand_company_registration.pdf
    ctx_brand_redline_v1.docx
  contract_packs/                # Phase 4.7 (NEW)
    v1.json
    v1_artifacts/
      contract.md                # source-of-truth markdown
      contract.docx              # python-docx render
      contract.pdf               # Puppeteer/pandoc render
    v2.json
    v2_artifacts/...
```

All gitignored. Raw uploads retained for life of deal; purged on archive.

Same file size caps as Phase 4.6: 25MB/file, 100MB/deal total. Larger files via `external_url`.

## Integration touchpoints

| Existing piece | How Phase 4.7 plugs in |
|---|---|
| **Phase 1 talent onboarding** | `talent.contract_template` block captured during onboarding. Optional `based_on_starter_template_id` traces provenance back to an agency starter. |
| **`talent.billing_entity`** | Legal entity merge fields (legal_name, country, tax_id, address, company_number) pull from here. Single source-of-truth — change once, all future contracts use new value. |
| **`talent.working_terms`** | Default usage rights, turnaround, revisions seed merge fields where deal-specific values are absent. |
| **Phase 4.6 proposal pack** | `commercial_proposal.confirmed_*` values (via `deal.proposal.*`) are primary source for commercial merge fields. `context_snapshot.proposal_pack_id_at_gen` captures which version. |
| **`deal.proposal.*`** | Canonical commercial values. fee_usd, deliverables, usage_rights_granted, exclusivity, timeline all flow through to contract merge fields. |
| **`deal.lead.discovery_debrief`** | Informs conditional clause evaluation (brand jurisdiction, special concerns surfaced). Frozen in context_snapshot.discovery_debrief_snapshot. |
| **`deal.contract.draft_contract_attachment_id`** | Auto-populated from `contract_pack.export_artifacts[].path` (contract.pdf) on Stage G render. The deal record stays canonical for the deal's contract reference. |
| **`deal.contract.amendment_log[]`** | Post-execution amendments use `trigger: amendment_request` to create a new contract_pack version. Each amendment_log entry's `contract_pack_version` field bidirectionally links to the contract_pack version that documented the amendment (parallel to `proposal.negotiation_log[].proposal_pack_version`). Anyone reviewing an amendment can navigate to the contract pack version that codified it. |
| **Phase 0 agency_profile** | Agency name, address, signatory info merge into contract. |
| **`data/contract_template_starters/`** | (gitignored) Agency-curated starter templates that Phase 1 onboarding copies + edits per talent. |
| **Phase 4.8 invoice pack** | Downstream artefact. On `deal.contract.contract_executed_at`, the orchestrator LLM-parses `commercial_proposal.llm_proposed.payment_terms` (e.g. "50% upon contract execution, 50% upon final delivery; NET-30") into a structured `deal.close.invoice_schedule[]`. Agent confirms once (gate). Each schedule entry then fires its own invoice_pack when its trigger_condition is met. The contract pack id is captured in `invoice_pack.context_snapshot.contract_pack_id_at_gen` for traceability. See `docs/invoice_workflow.md`. |

## Failure handling

| Failure | Behaviour |
|---|---|
| Required merge field has missing/low-confidence value | Added to `legal_review.blocking_issues[]`. Gate cannot pass until resolved (agent supplies value or downgrades field to non-required). |
| LLM cannot evaluate a clause condition confidently | Defaults to template's default_decision; flags decision with confidence note; agent reviews. |
| Talent template references merge field with no definition | Compose stage logs warning; placeholder left as `{{field}}` in composed markdown; surfaces as blocking_issue. |
| Conditional block references clause_id with no applicability rule | Defaults to `exclude` with rationale "no applicability rule defined"; logged. |
| python-docx fails on markdown table | Falls back to plain-text table representation; Word file still renders; agent can edit. |
| Puppeteer PDF render fails | Retry 2x; on final failure, status=failed; agent can use Word→PDF manually. pandoc as v0.2 fallback renderer. |
| Brand legal entity not provided | Cannot generate parties section. Stage B surfaces blocking_issue: "Brand legal entity required — upload company registration or enter manually." |
| Template_version changed mid-deal | Existing contract packs stay anchored via context_snapshot.template_version_used. New v(N+1) generation uses current template; agent sees a diff in UI. |
| Agent edits post-approval but forgets to re-approve before sending | UI blocks "Send" if `approved_at` is older than most recent edit. Hard block. |
| Brand sends redlined version | Agent uploads as `brand_redline` artefact + clicks "Respond to redline". Triggers `brand_redline_response` regen targeting the redlined sections. LLM diffs the brand's edits vs prior version and surfaces a structured change list for agent review. |
| Talent signs but contract has merge field placeholder | Detection: composed_markdown has unfilled `{{...}}`. Pre-render check blocks gate-pass with explicit error. |

## Cost profile

Per-pack: 4-6 Sonnet passes (artefact summary + merge field extract + clause evaluate + narrative draft + compose). Heavily cached from proposal pack context (talent profile + deal data already in cache from Phase 4.6 work). ~30-40k input tokens + ~10-15k output tokens (less than proposal — contract is more deterministic; narrative sections are bounded). Estimated **$0.20-0.40 per generation**. Negotiation iteration cost: typical deal sees 1-3 contract versions.

## v0.1 explicit non-goals

- **E-sign API integration.** v0.1 = manual PDF send + manual `talent_signed_at` / `brand_signed_at` capture. v2 = DocuSign / PandaDoc / HelloSign with webhook-driven signed_at population (already noted in Phase 4 vendor roadmap).
- **Multi-jurisdiction templates.** v0.1 = one template per talent. v0.2 if a talent operates across legal jurisdictions (e.g. US + UK contracts) — multiple template variants per talent with applicability rules.
- **Brand-side legal review feedback automation.** Brand redlines arrive as uploads; system diffs but doesn't auto-route to brand's legal team.
- **Contract redlining UI.** No Word-style track changes between versions. v0.2.
- **AI-generated legal opinion / risk assessment.** Out of scope.
- **Template marketplace.** Agencies sharing templates across other agencies — v0.2+.
- **Agency-wide template (vs per-talent).** Locked at per-talent for v0.1 per design decision. v2 could add an agency-level fallback if a talent hasn't completed onboarding template setup.

## v0.2 open questions

1. **Brand-side legal review automation** — when brand uploads a redlined version, can we auto-classify the redlines (acceptable / negotiable / rejected) the same way Phase 3b classifies cold replies? Would accelerate the negotiation loop.
2. **Counter-template handling** — when brand insists on their own contract template, we currently can't generate from it. v0.2 could parse the brand's template + map our merge fields into theirs.
3. **Amendment workflow** — post-execution amendments currently use the same pipeline with `trigger: amendment_request`. Should amendments have their own simplified UI (skip merge extraction since values already known; just narrative + clause edits)?
4. **Multi-talent contracts** — for campaigns with multiple talent (rare but real), one contract with multiple parties. Schema needs extension.
5. **Contract analytics** — which clauses get pushed back on most across all deals? Feeds back into per-talent template refinement. v0.2.
6. **Auto-import counter-signed PDF detection** — when brand returns a signed PDF, parse + diff vs sent version to detect any silent changes. Surface to agent for review before accepting as final.
7. **Structured condition evaluation** — v0.1 uses LLM to interpret natural-language conditions in `clause_applicability_rules[].condition`. v0.2 could add JSONLogic for deterministic evaluation of clear-cut conditions (e.g. `{"==": [{"var": "deal.proposal.exclusivity.duration_days"}, 0]}`), reserving LLM only for genuinely fuzzy conditions.
