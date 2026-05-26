# Contact Enrichment Workflow

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec for the system that takes a brand from "in our candidate list" to "we have N qualified named contacts with verified emails and decision-role tagging".

**Pairs with:**
- `docs/brand_discovery.md` — produces the brands this workflow enriches contacts for.
- `docs/brand_enrichment_workflow.md` — same shape and honesty policy, applied to brand records instead of people.
- `docs/brand_deals_workflow.md` (Phase 1.5) — past-deal records reference contacts here via `main_brand_contact_id`. When a contact at a brand later changes jobs (LinkedIn API picks up the move), we have a warm relationship at their new brand — surfaced as a `champion_internal_advocate` angle target. The past-deal record's `main_brand_contact_id` is what unlocks the warm-intro mapping.
- `docs/outreach_workflow.md` (Phase 3b) — consumes the contacts this workflow produces. Qualified contacts auto-enrol into AI-generated outreach sequences via Smartlead.
- `docs/vendor_roadmap.md` — the external services this workflow uses.
- `schemas/brand_contact.schema.json` — the contract for the output.

## Goal

For every active brand in the candidate pool, build a list of named contacts with:
- LinkedIn URL (primary identifier)
- Verified email where possible
- Title + function + seniority
- `decision_role` classification + rationale — 5 values: `buyer` / `influencer` / `gatekeeper` / `champion` / `unknown`. A CMO at a $50B+ brand is an `influencer`, NOT a `buyer`; the IM Manager 2 levels down is the actual buyer.
- Geographic location
- Tenure context

Plus placeholder records for known-important roles where the person hasn't been identified yet — so coverage gaps are visible, not hidden.

**Honesty floor:** never fabricate. Emails carry `verification_status` (`verified` / `catchall` / `guessed_pattern` / `unverified` / `bounced`). Unknown fields are omitted. Apollo data is licensed and stays in the gitignored output folder.

**Outreach hygiene:** CAN-SPAM-compliant by design (US project). Contacts who unsubscribe or ask to be removed get `do_not_contact: true` + `opt_out_at` set and are excluded from all outreach across all talents going forward. Per-talent pitch isolation prevents double-pitching the same person across two talents in a configurable 14-day window — basic anti-spam hygiene, not legal requirement.

---

## When this workflow runs

Three triggers:

| Trigger | When | Scope |
|---|---|---|
| **A. Auto-enrich on candidate promotion** | When a brand surfaces in `data/brand_candidates/current/{talent_id}.json` as `tier: primary` AND `qualification.tier ∈ [qualified, speculative]` AND no `data/brand_contacts/{brand_id}.json` exists yet | One brand at a time, in-flight after Brand Discovery completes |
| **B. Manual "find contacts" trigger** | User clicks "find contacts for X" in the UI | One brand on demand |
| **C. Refresh** | Quarterly per brand: re-verify emails (Apollo re-check); annually: re-pull LinkedIn data (handles new job moves) | Batched per-cron |

The orchestrator never auto-enriches brands the qualification gate has filtered out. Pitching contacts at brands that don't plausibly buy creator marketing is wasted Apollo credits.

---

## The 9-step pipeline (per brand)

### Step 1 — Identify target roles
**Reads:** the brand's record in `brand_industry_map.json` (`typical_campaign_tier`, `headcount`, `revenue`, `company_stage`).
**Logic:** the target role list scales with brand size.

| Brand profile | Target roles |
|---|---|
| `typical_campaign_tier: premium` AND `headcount ≥ 10000_plus` (large multinationals) | "Director of Influencer Marketing", "Head of Creator Partnerships", "VP Brand Marketing", "Senior Brand Manager — [talent's niche]", "Influencer Marketing Manager" |
| `typical_campaign_tier: macro` AND `headcount ∈ [1001_5000, 5001_10000]` | "Head of Influencer Marketing", "Brand Partnerships Manager", "Senior Brand Manager", "Social Media Director" |
| `typical_campaign_tier: mid` AND `headcount ∈ [201_500, 501_1000]` | "Marketing Manager", "Brand Manager", "Influencer Lead", "Head of Marketing", "Founder/CEO" (often still hands-on at this scale) |
| `typical_campaign_tier: micro` OR `headcount < 200` | "Founder", "CEO", "Head of Marketing", "Marketing Lead", "Anyone with 'marketing' in title" |
| Sensitive verticals (gambling, alcohol etc.) | Add "Compliance" / "Brand Safety" roles to capture stakeholders who could block a deal |

**Also pulled per-brand:** the brand's `creator_program_presence`. If `aspire`/`grin`/`ltk`/`shopmy` is listed, add "Creator Marketplace Lead" to targets. If `agency_of_record`, the talent's outreach goes via the AOR — add "Account Director at [AOR]" as a contact too.

**Output:** ordered list of target titles (highest-priority first).

### Step 2 — Apollo employee lookup
**Reads:** brand's `domain` from `brand_industry_map.json` + target titles from Step 1.
**Apollo query:**
```
people.search({
  organization_domains: [brand.domain],
  person_titles: [...target_titles],
  page_size: 25
})
```
**Output:** raw list of Apollo person records.
**Failure:** Apollo doesn't cover this brand (returns 0 hits) → continue to Step 3 with empty Apollo data; web search will be the primary source.

### Step 3 — LinkedIn API enrichment
**Reads:** Apollo hits from Step 2 + LinkedIn API (you provide).
**Two parallel calls:**

1. **Enrich Apollo hits** — for each Apollo `linkedin_url`, call LinkedIn API to confirm:
   - Person still works at this brand (Apollo data lags 3–6 months)
   - Current title (may have changed since Apollo cached it)
   - Last public activity date (informs `recent_linkedin_activity` signal)

2. **LinkedIn-native search** — for each target title not yet filled by Apollo, query LinkedIn API directly:
   ```
   linkedin.search_people({
     current_company: brand_name,
     title: target_title,
     limit: 5
   })
   ```
   Catches contacts Apollo misses (especially smaller brands and recent hires).

**Output:** merged contact records with confirmed `linkedin.{url, handle, last_activity, last_updated}` and freshness-checked titles.

### Step 4 — Web-search backup
**Reads:** target titles unfilled by Apollo + LinkedIn API.
**Logic:**
1. For each unfilled target title, run targeted **Exa** searches:
   - `"<brand> <title> site:linkedin.com"`
   - `"<title> at <brand>"`
   - `"<brand> announces head of <function>"` (catches PR announcements)
2. Use Exa `/contents` to extract the LinkedIn profile preview or PR text.
3. LLM (Claude Haiku) extracts: name, title, LinkedIn handle (if visible), public claims about role/scope.
**Output:** rough contact records — typically no email, no verified LinkedIn URL, lower confidence. Marked `source: exa_web_search` with confidence ≤ 0.50.

### Step 5 — Email verification
**Reads:** every contact record with an email from Steps 2–4.
**Logic:**
- **Apollo-sourced emails:** Apollo runs SMTP verification inline; respect their `verified` / `catchall` / `unverified` flag.
- **LinkedIn / web-search-sourced emails:** if no email returned, generate `guessed_pattern` from the brand's known pattern (`firstname.lastname@brand.com` is the common default — derived from existing verified emails at the brand).
  - Confidence flag: `guessed_pattern` is NOT a verified address. Outreach attempts mark it accordingly; bounce-back from a guess updates `verification_status: bounced` permanently for that pattern variant.
- **Bounced emails:** if `pitch_history` shows a recent hard bounce, set `verification_status: bounced` and skip future outreach until the contact is re-enriched.

**Output:** every email field has a `verification_status`. Records with unverifiable emails are kept (with status flagged) — never deleted.

### Step 6 — Decision-role classification
**Reads:** all contact records assembled so far + the brand's metadata (revenue, headcount, typical_campaign_tier, company_stage) + the contact's title + seniority.
**LLM call** (Claude Haiku, single prompt per contact):

Prompt template:
```
Brand: {brand_name}
- Revenue: {revenue}
- Headcount: {headcount}
- Typical campaign tier: {typical_campaign_tier}
- Company stage: {company_stage}

Contact:
- Title: {title}
- Seniority: {seniority}
- Function: {function}
- Tenure at brand: {tenure}

Classify this contact's likely role in approving a creator-marketing deal
in the {talent_rate_card_band} range. Choose ONE of:
  buyer | influencer | gatekeeper | champion | unknown

Provide a one-line rationale.

Definitions:
- buyer = can say yes AND holds the budget for this deal size (sign-off + spend).
- influencer = has input but no authority. Includes CMOs/VPs at megabrands
  (too senior to approve individual deals), brand managers (run the
  campaign), procurement/finance reviewers.
- gatekeeper = controls access to the buyer. EAs, agency-of-record account
  managers.
- champion = internal advocate / known fan of this talent or talent type.
- unknown = not enough signal to classify confidently.

Heuristic guidance:
- CMOs / VPs at $1B+ revenue brands → `influencer`, NOT `buyer`. Real
  sign-off happens 2-3 levels below at large brands.
- Influencer Marketing Manager / Director of Creator Partnerships at any
  brand size → typically `buyer` for deals within their authority band.
- Founders / CEOs at <500-person brands → typically `buyer` (sign-off
  and budget combined).
- Brand Manager / Senior Brand Manager → typically `influencer` (will
  run the campaign day-to-day but doesn't approve spend).
- Agency-of-record account directors → `gatekeeper` for the brand.
- Procurement / Finance reviewers → `influencer` (sign-off on contract
  terms, but the marketing-side buyer drives the spend decision).
```

**Output:** `decision_role` + `decision_role_rationale` per contact.
**Validation:** the LLM output is JSON-schema-checked against the contact $def's `decision_role` enum; invalid outputs trigger retry up to 3 times, then default to `unknown`.

### Step 7 — Placeholder generation
**Reads:** Step 1 target roles + Steps 2–4 actual contacts found.
**Logic:** any target role from Step 1 with no real contact found → create a placeholder:
```jsonc
{
  "contact_id": "{brand_id}-placeholder-{role-slug}",
  "name": { "full": "Unknown — {role}" },
  "is_placeholder": true,
  "title": "{role}",
  "function": "{inferred function}",
  "seniority": "{inferred seniority}",
  "decision_role": "{inferred from heuristics}",
  "qualification": { "score": <low>, "tier": "unqualified" },
  "qualification_filtered": true,
  "tags": ["coverage_gap"]
}
```
Placeholders are surfaced in the agency dashboard as "you have 3 unfilled IM Manager roles across 3 brands" so they can be manually filled.

### Step 8 — Dedup + merge
**Logic:** within a brand, two records may describe the same person (Apollo + LinkedIn often return the same contact from different angles). Merge by:

1. **Primary key:** `linkedin.url` exact match → merge.
2. **Secondary:** normalised name (lowercase, first+last) + same email domain → merge.
3. **Tertiary:** identical `email.address` → merge.

When merging:
- Prefer fields from the source with the highest confidence (LinkedIn API > Apollo > Hunter > web search > pattern_inferred).
- Always preserve workflow-state fields (`pitch_history`, `tags`, `notes`, `do_not_contact`) from the existing record — never overwrite during enrichment.
- Combine `verification_sources[]` from all sources (don't dedup; the audit trail is valuable).

**Cross-brand dedup:** the same LinkedIn URL appearing at two different brands → person moved jobs. Mark the old record as `tenure.is_current: false`; create new record at the new brand.

### Step 9 — Quality gates + write
Before writing `data/brand_contacts/{brand_id}.json`:

1. **Schema validation** — record conforms to `schemas/brand_contact.schema.json`.
2. **brand_id cross-check** — exists in `brand_industry_map.json`.
3. **Country-code validation** — `location.country` is ISO 3166-1 alpha-2 (where present).
4. **Honesty check** — every populated `email` has a `verification_status`; every record has at least one `verification_sources[]` entry.
5. **Workflow-state preservation** — if the file already existed, merge fresh discovery output with previous workflow state per the merge semantics in `schemas/brand_contact.schema.json`.

Failed gates → record goes to an `enrichment_review.json` queue (mirrors brand-enrichment policy), not the live file.

---

## Honesty-floor policy (applies to every step)

| Situation | Action |
|---|---|
| Vendor returns a verified value (e.g. Apollo SMTP-verified email) | Populate with `verification_status: verified` |
| Email built from a pattern but not SMTP-checked | `verification_status: guessed_pattern` — visible to user at outreach time |
| Vendor returns nothing for a field | **Omit the field.** Do not null, do not zero, do not guess |
| Two sources disagree (Apollo says VP, LinkedIn says SVP) | Prefer fresher source (`fetched_at` newer); note disagreement in `notes` |
| Person no longer at brand (LinkedIn shows different company) | Set `tenure.is_current: false`; do not delete record (history matters) |

---

## Outreach hygiene & vendor terms

US project; CAN-SPAM is the primary legal frame. The structures below are standard CRM/email-marketing good practice, not foreign-jurisdiction compliance.

| Practice | How we handle it |
|---|---|
| **Opt-out / unsubscribe** | Set `do_not_contact: true` + `opt_out_at`. Record stays in the file (audit trail + so we don't accidentally re-enrich and re-pitch them later) but is excluded from all outreach across all talents forever. CAN-SPAM requires honouring opt-out within 10 business days; we honour immediately. |
| **Source disclosure** | If a contact asks "how did you get my email", `verification_sources[]` records every vendor + date + fields they contributed — answerable in seconds. |
| **Vendor terms** | Apollo data is licensed under their terms; we don't redistribute outside our app. The `data/brand_contacts/` folder is gitignored, so vendor data never enters version control. Same for LinkedIn-derived data. |
| **Per-talent pitch isolation** | Default 14-day cooldown between pitches to the same contact across different talents in our roster. Prevents the contact from feeling spammed by us across multiple of our creators — protects deliverability + sender reputation. Configurable per-agency. |
| **Data quality** | Don't enrich fields we don't need on the first pass. Phone numbers, alternate emails, and personal social handles are opt-in per-brand at enrichment time — not pulled by default. Cleaner data + fewer storage costs. |
| **Bounce handling** | Hard bounces flip `email.verification_status` to `bounced` permanently for that address. No retry. Soft bounces tracked separately; 3 in a row → treated as hard. |

---

## Tools used per step

| Step | Tool / API | Cost | v0.1 status |
|---|---|---|---|
| 1. Target role identification | Code (rules-based) | Free | Built |
| 2. Apollo employee lookup | Apollo API `/people/search` + `/people/match` | ~$0.20–$0.50 per record | **Confirmed v0.1** |
| 3. LinkedIn enrichment + search | LinkedIn API (user-provided) | Per access agreement | **Confirmed v0.1** |
| 4. Web-search backup | Exa `/search` + `/contents` + Claude Haiku extraction | Exa quota + Haiku tokens | **Confirmed v0.1** (already in use for brand discovery Search 15) |
| 5. Email verification | Apollo inline for Apollo-sourced; pattern-inferred for others | Included in Apollo cost | **Confirmed v0.1** |
| 6. Decision-role classification | Claude Haiku 4.5 | ~$0.001 per contact | **Confirmed v0.1** |
| 7. Placeholder generation | Code (rules-based) | Free | Built |
| 8. Dedup + merge | Code | Free | Built |
| 9. Quality gates + write | Code + schema validation | Free | Built |

**Total v0.1 vendor footprint added:** Apollo + LinkedIn API. Exa + Anthropic SDK already in use.

**v2 vendor additions (deferred — see `docs/vendor_roadmap.md`):**
- **Hunter.io** as a parallel email-verification source — catches brands Apollo misses, more affordable for high-volume.
- **Clay.com** as a multi-source orchestrator — aggregates Apollo + Hunter + LinkedIn + Twitter under one API; per-record pricing makes it good for spiky/unpredictable contact volume.
- **RocketReach** as an Apollo alternative — different coverage profile, especially in EU markets.

---

## Orchestration: how this fits with Brand Discovery

**Trigger sequence on talent profile save (per `docs/onboarding_workflow.md` Step 9):**

```
talent profile saved
    │
    ├─ Step 9A: similar-talent AI research (existing) ─┐
    │                                                  │
    └─ Step 9B: Brand Discovery first run ─────────────┤
                    │                                  │
                    ▼                                  │
        For each candidate where                       │
        tier: primary AND                              │
        qualification.tier ∈ [qualified, speculative]: │
                    │                                  │
                    ▼                                  │
        Contact Enrichment pipeline ◄──────────────────┘
                    │
                    ▼
        data/brand_contacts/{brand_id}.json
                    │
                    ▼
        UI dashboard surfaces contacts for outreach
```

**Triggering modes:**

- **Mode 1: In-flight after Brand Discovery** — when Brand Discovery completes for a talent, automatically enrich contacts for the top 10–20 primary-tier qualified candidates. Runs in parallel per-brand (rate-limited against Apollo). Latency: 30–90 seconds per brand.
- **Mode 2: Manual** — user clicks "find contacts" for a specific brand from the UI. Runs synchronously; latency 30–60 seconds.
- **Mode 3: Refresh** — quarterly cron re-verifies all emails; annual cron refreshes LinkedIn data for active contacts (re-runs Steps 3–5 only).

---

## State machine

```
BRAND PROMOTED TO PRIMARY-TIER CANDIDATE
        │
        ▼
   ┌─────────────────────┐
   │ Step 1              │ ← Identify target roles from brand metadata
   └─────────────────────┘
        │
        ▼
   ┌─────────────────────────────┐
   │ Steps 2–4 in parallel:      │
   │   Apollo lookup             │
   │   LinkedIn enrichment       │
   │   Web-search backup         │
   └─────────────────────────────┘
        │
        ▼
   ┌─────────────────────┐
   │ Steps 5–6 sequential│ ← Email verify, then decision-role classify
   └─────────────────────┘
        │
        ▼
   ┌─────────────────────┐
   │ Step 7              │ ← Create placeholders for unfilled targets
   └─────────────────────┘
        │
        ▼
   ┌─────────────────────┐
   │ Step 8              │ ← Dedup + merge with existing records
   └─────────────────────┘
        │
        ▼
   ┌─────────────────────┐
   │ Step 9              │ ← Validate, then atomic write
   └─────────────────────┘
        │
        ├─ FAIL → enrichment_review.json + human review
        │
        └─ PASS → write to data/brand_contacts/{brand_id}.json
                    + log run_metadata + emit "contacts_enriched" event
```

---

## Failure handling

| Failure | Behaviour |
|---|---|
| Apollo quota exhausted | Pause for this brand; record in `enrichment_meta.errors`; UI surfaces "Apollo budget reached this month" |
| Apollo returns 0 hits for the brand | Skip Step 2; proceed with Steps 3–4. Brand may genuinely be too small for Apollo (often the case for nano-tier D2C). |
| LinkedIn API rate limited | Exponential backoff (3 attempts); on persistent failure, skip Step 3 — Apollo data is used as-is, marked as stale-risk |
| Exa quota exhausted | Skip Step 4; only Apollo + LinkedIn-sourced contacts are captured this run |
| LLM classification returns invalid `decision_role` | Retry 3 times; if still invalid, default to `unknown` and flag for review |
| Email verification (Apollo) returns "bounced" | Set `verification_status: bounced`; never retry until a new email is supplied for this contact |
| Same person appears at two brands with `is_current: true` on both | Anomaly — flag for human review; possible LinkedIn lag or genuine dual role |
| New contact has same `email.address` as an existing contact at a different brand | Different person at different brand sharing a personal/legacy email — keep both records; flag in `notes` |

---

## Per-contact and per-brand statistics

The `brand_contacts/{brand_id}.json` file's `enrichment_meta` block carries run-level stats. The orchestrator also computes roster-wide aggregates after each run:

| Metric | Used for |
|---|---|
| `contacts_total` per brand | Coverage gauge |
| `contacts_qualified` per brand | Pitch-readiness (≥1 qualified contact = brand is reachable) |
| `coverage_gaps` per brand | Number of placeholder roles still unfilled |
| `total_apollo_credits_used_per_run` | Cost monitoring |
| `total_contacts_enriched_per_run` | Throughput monitoring |

These feed into:
- The brand candidates UI (a brand with 0 qualified contacts gets a "needs contact discovery" badge).
- The agency dashboard's monthly summary.

---

## Open questions for v0.2

1. **LinkedIn API scope** — depends on which API you're providing access to. Standard LinkedIn (REST), Sales Navigator API, or partnership-tier. Schema accommodates all; workflow steps may need tightening once scope is known.
2. **Pitch template schema** — `pitch_history.template_id` references a template, but templates aren't yet defined. Likely a Phase 3b spec — proposed new files `schemas/pitch_template.schema.json` and `docs/outreach_workflow.md` (not yet written; deliverables for the next phase).
3. **Contact-to-talent fit overlay** — should we score a contact specifically *for a given talent* (e.g. this contact has previously approved deals with similar-tier creators)? My recommendation: keep the contact's absolute qualification stable; compute per-talent overlay at pitch time from `pitch_history` and `champion_for_talents`.
4. **Email-deliverability infrastructure** — once we have verified emails, who actually sends? Resend / SendGrid / Postmark / direct SMTP from the creator's own domain? Direct from the creator's domain is best for deliverability but operationally complex. Phase 3.5 decision.
5. **Cross-talent contact-fatigue protection** — beyond the 14-day cooldown, should we cap total contacts pitched per week per talent (deliverability + agency reputation)? Probably yes; tunable per-talent.
6. **Manual override layer** — if a user manually corrects a contact's `decision_role` (e.g. flips an LLM-assigned `influencer` to `buyer` because they have inside knowledge), the next enrichment cycle must respect that. Propose: `field_overrides[]` array similar to the brand-enrichment v0.2 proposal.
7. **Champion-detection automation** — when a talent has a verified prior campaign with a contact, auto-set `champion_for_talents` to include that talent_id. Today this requires manual tagging; should be derived from `pitch_history` where `outcome: meeting_booked` or later.
8. **AOR (Agency of Record) handling** — when a brand has `creator_program_presence: ["agency_of_record"]`, contacts at the AOR are gatekeepers. Currently captured as separate contacts at the AOR brand_id. Worth modelling AOR relationships explicitly (e.g. `agency_of_record_for: ["nike", "adidas"]` on a contact at the AOR).
