# Agency Setup Workflow (Phase 0)

**Status:** Draft v0.1 (2026-05-26). One-time setup performed BEFORE any talent is onboarded. Establishes the agency identity, the primary agent's sender mailbox, DNS records, and the signature template baked into every outreach email.

**Pairs with:**
- `schemas/agency_profile.schema.json` — the data contract.
- `docs/onboarding_workflow.md` — talent onboarding runs AFTER agency setup is complete.
- `docs/outreach_workflow.md` — every outreach email sends from the agency's mailbox in the agent's name.
- `docs/vendor_roadmap.md` — Smartlead mailbox setup happens here.

## Goal

Establish the agency operating the system as the **sender identity for all outreach**. v0.1 assumes a single agency with a single primary agent. Emails to brand contacts come from `{agent_first_name}@{agency_domain}` in the agent's name; voice is **agent-led on-behalf-of talent** ("I'm Sarah from Native Agency — I represent Jane Doe, who drove 1.24M reach for Gymshark...").

v2 will lift the single-agent constraint to multi-agent rosters; the schema is already array-shaped to absorb this without a breaking change.

## Why a separate phase

The agency setup is fundamentally different from talent onboarding:
- It happens once, not per talent
- It involves DNS + domain configuration (one-time)
- It involves a 2-4 week sender-domain warmup that must complete before any cold outreach can send
- The agency identity is shared across the whole roster; talents are added to an already-warmed-up sender

Doing this as Phase 0 rather than embedding it in talent onboarding means: (a) the first talent doesn't wait 2-4 weeks for warmup before any outreach can go out; (b) the DNS records are the agency's concern, not each talent's.

## The 9-step setup

### Step 1 — Agency identity
Collect:
- `name` — display name used in signatures + email intros
- `domain` — the agency's primary domain (e.g. `nativeagency.com`). Must be a domain the agency controls (DNS access required in Step 3).
- `website_url`
- `company_address` — physical mailing address. **REQUIRED for CAN-SPAM compliance** (every cold email must include the sender's physical address in the footer)

### Step 1.5 — Visual branding
Collect the visual identity that every downstream agency-branded artefact will use — discovery-call prep decks (Phase 4.5), proposal decks (Phase 4 PROPOSAL), case-study leave-behinds, signature blocks. Stored under `agency_profile.branding`:

- `logo_url` — primary logo (transparent PNG recommended, 500-1000px wide). Web-accessible URL or local path.
- `logo_dark_url` (optional) — variant for dark backgrounds
- `primary_color`, `secondary_color`, optional `accent_color` — hex format `#RRGGBB`. Used for slide titles, headings, accent shapes, KPI callouts.
- `background_color` (default `#FFFFFF`), `text_color` (default `#1A1A1A`)
- `font_family_heading`, `font_family_body` — CSS font-family stacks
- `google_fonts` (optional) — array of Google Font family names to auto-load
- `tagline` (optional) — positioning line for title slides + signature footers
- `deck_template_id` — defaults to `default`; v2 supports custom templates

**Why capture here, not later:** branding is required input to every generated agency artefact. Capturing it once at agency setup means the discovery-prep generator, proposal-deck generator, and signature renderer all pick up the same values automatically. A rebrand later updates the block once and propagates to all future generations.

**v0.1 minimum:** logo_url + primary_color + font_family_heading + font_family_body. Everything else has sensible defaults.

### Step 2 — Primary agent
Collect for the single v0.1 agent:
- `agent_id` (slug — usually derived from name)
- `name` — full name as it appears in the FROM line + signature
- `email` — primary inbox; replies route here
- `phone` — for signature
- `title` — for signature (e.g. "Director of Brand Partnerships")
- `linkedin_url` — for signature (optional but recommended)
- `is_primary: true` (always true in v0.1)
- `represents_talent_ids: []` — v0.1: empty array signals "represents all talents"; v2 will populate explicit assignments

### Step 3 — DNS records for sender domain
The agency adds three DNS records to their domain. The UI generates the exact values via Smartlead and shows them in copy-paste boxes:

| Record | Type | Purpose |
|---|---|---|
| **SPF** | TXT | `v=spf1 include:smartlead.io ~all` — authorises Smartlead to send on behalf of the agency's domain |
| **DKIM** | TXT | Generated per-domain by Smartlead; signs outgoing mail. Required for DMARC alignment |
| **DMARC** | TXT | `v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@{agency_domain}` |

UI then validates each record via Smartlead's verification endpoint. The user can't proceed until all three show ✓ verified.

### Step 4 — Sending mailbox provisioning
Provision the sending mailbox:
- Mailbox address: typically `{agent_first_name}@{agency_domain}` (matches the agent's identity)
- Smartlead onboards the mailbox; returns a `smartlead_mailbox_id`
- `daily_send_cap` defaults to 50 for the first 7 days of warmup, ramping to 200/day at full warmup
- Mailbox stored at `agency_profile.sending_mailboxes[0]` with `purpose: "named_agent_outreach"`

### Step 5 — Signature template
The user customises the signature template that's appended to every outreach email. UI provides a default + lets them edit:

```
Default template:
{agent_name}
{agent_title} | {agency_name}
{agent_email} · {agent_phone}
{agency_website}

To unsubscribe: {unsubscribe_link}
{agency_address}
```

**Required elements** (validated):
- `{unsubscribe_link}` — CAN-SPAM compliance
- `{agency_address}` — CAN-SPAM compliance
- `{agent_name}` — identifies the human sender

The orchestrator validates these tokens are present when the user saves.

### Step 5.5 — Invoice template
Captures the agency-wide invoice template used by the Phase 4.8 invoice pack generator (`docs/invoice_workflow.md`). Stored under `agency_profile.invoice_template`. Single template for all talent + deals — talent-specific billing entity comes from `talent.billing_entity` at generation; brand entity from `contract_pack.context_snapshot.brand_legal_entity_at_gen`.

**Captured:**
- `markdown_source` — invoice body template with `{{merge_field}}` placeholders. Optional `{{narrative_line_items}}` enables LLM-drafted per-line-item descriptions. Default starter template provided that agencies can edit.
- `invoice_number_prefix` (default `INV-`) + `invoice_number_format` (default `INV-{YYYY}-{seq:04d}` → `INV-2026-0042`)
- `invoice_number_sequence` — auto-incrementing per-agency counter (initialised to 1 unless agency is importing from a prior system, in which case set to current sequence to maintain continuity)
- `default_payment_terms_days` (default 30 — i.e. NET-30) + `due_date_calculation` (calendar_days or business_days)
- `tax_handling` enum (`none` / `vat_inclusive` / `vat_added` / `sales_tax`) + `default_tax_rate` decimal + `tax_label`
- `payment_instructions_markdown` — bank details / IBAN / SWIFT / Stripe link / PayPal address. Free-text supporting merge fields (e.g. `{{invoice_number}}` as bank reference)
- `invoice_footer` — late-payment legal text (optional)
- `template_version` + `template_updated_at` — bumped on any change; captured in `invoice_pack.context_snapshot.agency_invoice_template_version` for traceability

**Why capture here, not later:** invoices are highly deterministic — most of the template variation is at agency level (numbering scheme, tax treatment, payment instructions). Capturing once at agency setup avoids per-talent or per-deal re-config. Talent-specific fields (billing entity legal name) auto-pull from existing `talent.billing_entity` data.

**v0.1 minimum:** payment_instructions_markdown + invoice_number_prefix + default_payment_terms_days. Everything else has sensible defaults.

### Step 6 — Mailbox warmup (background, 2-4 weeks)
Smartlead's peer-to-peer warmup network starts gradually building sender reputation:
- Day 1-7: 5-10 emails/day to other warmed inboxes; replies, opens, marks-as-important
- Week 2-3: ramp to 50-100/day
- Week 4: full capacity per `daily_send_cap`

`warmup_status` lifecycle in the schema:
```
pending          (DNS not verified yet)
   │
   ▼
in_progress      (warmup running; Smartlead managing)
   │
   ▼
complete         (ready for cold outreach)
```

**Cold outreach is BLOCKED until `warmup_status == "complete"`.** UI surfaces "Warming up — N days remaining" on the dashboard. Talents can still be onboarded during this window; their outreach queues up.

### Step 7 — Final validation + save
- Schema-validate `agency_profile.json` against `schemas/agency_profile.schema.json`
- Verify all three DNS records still showing ✓
- Save `data/agency_profile.json` (gitignored — contains real agent contact info)
- Mark agency status as "active" — talent onboarding now permitted

## State machine

```
   ┌──────────────┐
   │  not_started │
   └──────┬───────┘
          │ Step 1-2 complete
          ▼
   ┌────────────────────┐
   │  awaiting_dns      │ ← user adds DNS records
   └──────┬─────────────┘
          │ Step 3 DNS verified
          ▼
   ┌────────────────────┐
   │  warming_up        │ ← Step 4-6 running (~2-4 weeks)
   └──────┬─────────────┘
          │ warmup_status: complete
          ▼
   ┌────────────────────┐
   │  active            │ ← Talent onboarding permitted;
   └────────────────────┘   cold outreach can send
```

## Integration with other phases

| Where | How agency profile is used |
|---|---|
| `docs/onboarding_workflow.md` — talent onboarding | Per-talent sender domain setup is **REMOVED**. Talents use the agency's pre-warmed mailbox. Onboarding simplifies. |
| `docs/outreach_workflow.md` — email generation | Every email's `smartlead_meta.sending_mailbox` resolves to `agency_profile.sending_mailboxes[0].email`. Email body's signature template merges from `agency_profile.default_signature_template` with `{agent_*}` and `{agency_*}` fields populated. |
| Pitch generation prompt construction | LLM prompt includes: `"You are writing on behalf of {talent_name}, who is represented by {agent_name} at {agency_name}. Voice: agent-led on-behalf-of."` This locks the voice mode for v0.1. |
| Reply handling | All replies route to `agency_profile.agents[0].email`. The agent classifies + handles all inbound across the roster. |
| Reply classification + kill | Same as before, but the kill applies across the agency's roster (not per-talent), since the agency sender shouldn't be perceived as spamming the same contact for two creators in quick succession. |

## v2 changes (deferred)

When v2 adds multi-agent support:
- `agents[]` `maxItems` lifts from 1 to no limit
- `sending_mailboxes[]` expands — typically one per agent
- `agents[].represents_talent_ids[]` becomes meaningful: each talent's outreach uses their assigned agent's mailbox + signature
- New onboarding sub-step: "Add an agent to the roster" with the same DNS-already-done shortcut (new agents share the agency's domain reputation; only need a new mailbox warmed)
- Cross-roster kill becomes per-agent-aware (replies to Sarah only kill Sarah's active enrollments, not Tom's)

## Failure handling

| Failure | Behaviour |
|---|---|
| DNS record not verifying after 30 min | UI prompts user to check propagation; some DNS providers take up to 48h. Block warmup start until verified. |
| Domain reputation pre-poisoned (the agency's domain has been used for spam in the past) | Smartlead flags during warmup; user notified; options: switch to a fresh subdomain (`outreach.agency.com`) or new domain. |
| Mailbox warmup hits a quality issue (low engagement during warmup) | Pause warmup; surface diagnostics; manual intervention (often: send a few real emails from the inbox to seed positive signals). |
| User wants to change agent name after warmup is complete | Allowed but UI warns: a sudden change in From-name on a warmed mailbox may cause Gmail to throttle. Recommend a 7-day overlap period with both names visible. |
| Signature template missing required tokens at save | Validation fails inline; UI highlights missing `{unsubscribe_link}` / `{agency_address}` / `{agent_name}`. |

## Open questions for v0.2

1. **Multi-domain support for one agency** — some agencies want a separate sending domain per vertical (e.g. `partnerships.agency.com` for one type of pitch, `outreach.agency.com` for another). v0.2 may add multiple sending domains under one agency.
2. **Re-warmup after extended pause** — if an agency mailbox sits unused for 60+ days, deliverability may degrade. v0.2: auto-detect inactivity and prompt for a re-warmup cycle.
3. **Agency-level analytics** — total emails sent / reply rates / costs across the whole agency. Currently rolls up from per-talent analytics in `scripts/analyze_outreach.py`; could surface as an agency dashboard in v0.2.
4. **Signature A/B testing** — try different signature formats (with/without phone, with/without LinkedIn URL) to see which produces higher reply rates. v0.2 with two `default_signature_template` variants.
