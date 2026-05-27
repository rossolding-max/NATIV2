# Generic Contract Template Starter — Example Scaffold

> **Purpose:** illustrative example showing the conventions used by NATIV2's contract pack pipeline (Phase 4.7). NOT legal advice. Agencies adopting this should have their lawyer review + adapt to their jurisdiction + commercial practices.
>
> **Conventions demonstrated:**
> - `{{merge_field}}` — deterministic values extracted from talent / agency / deal records
> - `{{#if condition}}...{{/if}}` — conditional clauses evaluated against `clause_applicability_rules`
> - `{{narrative_*}}` — narrative placeholders the LLM drafts during Stage D
>
> **Pairs with:** `schemas/talent.schema.json` § contract_template + `docs/contract_pack_workflow.md` + `docs/data_lineage.md` GAP-10.

---

# INFLUENCER COLLABORATION AGREEMENT

**Between:**

**The Talent:**
{{talent_legal_name}}
{{talent_address}}
({{#if talent_tax_id}}Tax ID: {{talent_tax_id}}; {{/if}}"Talent")

**And the Brand:**
{{brand_legal_name}}
{{brand_address}}
({{#if brand_tax_id}}Tax ID: {{brand_tax_id}}; {{/if}}"Brand")

**Dated:** {{contract_date}}

---

## 1. Engagement

The Talent agrees to create and deliver the following content (the "Deliverables") for the Brand's campaign ("{{campaign_name}}"):

{{deliverables_table}}

{{narrative_engagement_context}}

## 2. Fee

**Total fee:** {{fee_currency}} {{fee_amount}}

**Payment schedule:**
{{payment_schedule_breakdown}}

{{narrative_payment_rationale}}

## 3. Usage Rights

**Granted to Brand:** {{usage_rights_description}}
**Duration:** {{usage_duration_days}} days from first publication
**Territories:** {{usage_territories}}
**Channels:** {{usage_channels}}

{{#if whitelisting_granted}}
### 3.1 Whitelisting / Paid Amplification

Brand may amplify the Deliverables as paid advertising via the Talent's social handle(s) for {{whitelisting_duration_days}} days from first publication, subject to Talent's pre-approval of each individual creative variant.
{{/if}}

## 4. Exclusivity

{{#if exclusivity_required}}
Talent agrees not to publish promoted content for {{exclusivity_competitor_categories}} during the {{exclusivity_duration_days}}-day exclusivity period commencing {{exclusivity_starts_at}}.
{{/if}}

{{#if no_exclusivity}}
No exclusivity restrictions apply.
{{/if}}

## 5. Approval & Revisions

Brand has {{approval_window_hours}} hours to approve or request revisions to each Deliverable. Talent includes {{revisions_included}} revision round{{#if revisions_included_plural}}s{{/if}} per Deliverable; additional rounds at {{additional_revision_fee_currency}} {{additional_revision_fee_amount}} each.

{{narrative_revisions_context}}

## 6. Posting Schedule

Talent agrees to publish the Deliverables according to the following schedule:

{{posting_schedule_table}}

Posting dates may be adjusted by mutual agreement in writing (including email).

## 7. Talent Obligations

7.1 Talent will create original content reflecting Talent's authentic voice + audience expectations.

7.2 Talent will comply with the Brand's reasonable creative guidelines (provided in writing in advance).

7.3 **Disclosure ({{disclosure_style}}):** Talent will disclose the commercial nature of the Deliverables in compliance with applicable advertising standards:
- For {{disclosure_style}} jurisdiction: include `#ad` (or equivalent platform-specific disclosure) prominently in caption + (where platform supports) the platform's built-in paid-partnership tag.
{{#if campaign_hashtags_required}}
- Include the following campaign hashtags as primary tags: {{campaign_hashtags_formatted}}.
{{/if}}

7.4 Talent will not make claims about Brand's products beyond what Brand has expressly authorised in writing.

## 8. Brand Obligations

8.1 Brand will pay the Fee in accordance with Section 2.

8.2 Brand will provide the campaign brief, product (if applicable), and any reference materials at least {{brand_brief_lead_time_days}} days before the first posting date.

8.3 Brand will respond to revision requests within the approval window.

{{narrative_brand_obligations_extra}}

## 9. Intellectual Property

9.1 Talent retains ownership of all copyright in the Deliverables.

9.2 Talent grants Brand the usage rights specified in Section 3.

9.3 Outside the granted rights, Brand may not modify, redistribute, sub-licence, or transfer the Deliverables without Talent's prior written consent.

{{#if ip_assignment_required}}
### 9.4 Specific IP Assignment

Notwithstanding 9.1, Brand obtains exclusive assignment of any product-specific creative concepts, mascot designs, jingles, or trademarks created specifically for this campaign as set out in Schedule A.
{{/if}}

## 10. Confidentiality

Each party agrees to keep confidential the other's non-public information for {{confidentiality_duration_years}} years from the date of this Agreement, except where disclosure is required by law.

## 11. Termination

11.1 Either party may terminate for material breach with 14 days' written notice + opportunity to cure.

11.2 If Brand terminates without cause after Talent has commenced work, Talent retains the portion of the Fee proportionate to work completed plus a {{kill_fee_pct}}% kill fee on the unfinished portion.

{{narrative_termination_rationale}}

## 12. Liability

Each party's aggregate liability under this Agreement is capped at the Fee amount, except for breaches of confidentiality, indemnity obligations, or wilful misconduct.

{{#if brand_required_indemnity}}
### 12.1 Brand Indemnity

Brand indemnifies Talent against claims arising from the Brand's products, claims, or supplied materials.
{{/if}}

## 13. Force Majeure

Neither party is liable for delay or non-performance caused by events beyond reasonable control (incl. acts of god, pandemic, governmental action, platform outages exceeding 24 hours).

## 14. Governing Law

This Agreement is governed by the laws of {{governing_law}} and the parties submit to the exclusive jurisdiction of the courts of {{jurisdiction}}.

## 15. Notices

Notices may be served by email to:
- **To Talent:** {{talent_notice_email}}
- **To Brand:** {{brand_notice_email}}

## 16. Entire Agreement

This Agreement (including any Schedules) constitutes the entire agreement between the parties on this subject + supersedes all prior negotiations + understandings.

---

**SIGNED for and on behalf of TALENT:**

Signature: ___________________________
Name: {{talent_signatory_name}}
Title: {{talent_signatory_title}}
Date: ___________________________

**SIGNED for and on behalf of BRAND:**

Signature: ___________________________
Name: {{brand_signatory_name}}
Title: {{brand_signatory_title}}
Date: ___________________________

---

## Notes for the agency adopting this template

This scaffold demonstrates **three placeholder types** the contract pack pipeline recognises:

### 1. `{{merge_field}}` — deterministic substitution

Values extracted via Stage B from talent / agency / deal records. Examples used above:
- `{{talent_legal_name}}` ← `talent.billing_entity.legal_name`
- `{{brand_legal_name}}` ← `brand_industry_map.brands[brand_id].legal_entity.legal_name` (or `brand_candidate.legal_entity_override`)
- `{{fee_amount}}` ← `deal.proposal.fee_usd`
- `{{usage_duration_days}}` ← `deal.proposal.usage_rights_granted.duration_days`
- `{{disclosure_style}}` ← `talent.disclosure_defaults.style`
- `{{campaign_hashtags_formatted}}` ← `deal.delivery.campaign_hashtags[]` joined with " "
- `{{governing_law}}` ← `talent.contract_template.default_governing_law` (or deal-specific override)

Define each in `talent.contract_template.merge_field_definitions` with source path + default + transform (e.g. "join with comma + space" for arrays).

### 2. `{{#if condition}}…{{/if}}` — conditional clauses

Stage C evaluates each `{{#if}}` block via LLM against `clause_applicability_rules`. Examples used above:
- `{{#if talent_tax_id}}` — include when talent_tax_id is non-empty
- `{{#if whitelisting_granted}}` — include when `deal.proposal.usage_rights_granted.whitelisting_allowed` is true
- `{{#if exclusivity_required}}` — include when `deal.proposal.exclusivity.duration_days > 0`

Define each in `talent.contract_template.clause_applicability_rules` with the rule expression + applicability rationale template.

### 3. `{{narrative_*}}` — LLM-drafted narrative

Stage D fills these via LLM with declared sources + word count budget. Examples used above:
- `{{narrative_engagement_context}}` — 30-60 word framing of the engagement
- `{{narrative_payment_rationale}}` — 20-40 word framing of payment schedule rationale
- `{{narrative_revisions_context}}` — 20-40 word note about the revisions discipline
- `{{narrative_brand_obligations_extra}}` — 0-100 word brand-specific obligations from discovery debrief
- `{{narrative_termination_rationale}}` — 20-50 word framing of the termination structure

Define each in `talent.contract_template.narrative_placeholders` with sources_to_draw_from + word_count_min/max.

---

## What this scaffold deliberately doesn't include

- **Insurance / liability cover** (varies hugely by jurisdiction + agency)
- **Tax / VAT handling** (use `agency_profile.invoice_template.tax_handling` not the contract for this)
- **GDPR / data processing agreement** (add as conditional clause `{{#if brand_in_eu}}` against a Data Processing Addendum schedule)
- **Specific platform terms** (e.g. Meta's Branded Content Policy) — your agency's compliance officer should determine which to include
- **Performance KPI commitments** — talent should rarely guarantee reach/engagement (platform algorithms are unpredictable); use `narrative_brand_obligations_extra` to spell out best-efforts commitments instead

---

## How to onboard this template

1. **Lawyer review** the markdown above + adapt to your jurisdiction.
2. Save the adapted version to S3 under `agencies/{agency_id}/contract_template_starters/{template_id}.md`.
3. During talent onboarding (Phase 1 Step 7.5), reference the starter template by ID; the talent's `contract_template.based_on_starter_template_id` captures provenance.
4. Talent-specific overrides happen via talent's questionnaire (e.g. talent's preferred kill_fee_pct; talent's required disclosure_style).
5. The contract pack pipeline (Phase 4.7) uses the talent's adopted version — starter changes do NOT automatically propagate (intentional — talents shouldn't have legal terms changed without their consent).
