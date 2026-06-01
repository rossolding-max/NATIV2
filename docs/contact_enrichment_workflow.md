# Contact Enrichment Workflow

**Status:** v0.1 shipped M8 (2026-05-26); reshaped M8.1 (2026-06-01) into broad Phase A capture + classify+recommend Phase B + user-gated bulk-reveal Phase C. Spec below reflects M8.1; M8 narrow-titles + per-row pre-revealed-emails behaviour deprecated.

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

## M8.1 — Three-phase shape

The workflow splits into three phases with a human-in-the-loop gate
between Phase B and Phase C. The expensive Apollo email-reveal call
fires only on contacts the operator explicitly selects:

| Phase | Trigger | Cost shape |
|---|---|---|
| **A. Broad capture** | `POST /api/v1/brands/{brand_id}/contact-enrichment/run` (manual) | Apollo `/people/search` (no email; per-query cost, not per-record); LinkedIn enrich; Exa fallback. ~$0.30-0.80 per brand. Surfaces 30-80 marketing-adjacent contacts. |
| **B. Classify + recommend** | Same Celery task continues; runs Step 6 batched Haiku call | ~$0.01-0.02 per brand. Sets `decision_role` + `outreach_recommendation` on every contact. |
| **C. Bulk reveal (operator-selected)** | `POST /api/v1/brands/{brand_id}/contact-emails/reveal` with `{contact_ids: [...]}` | Apollo `/people/match` fires per selected contact (~$0.20-0.50 each). 60/min rate limit → 20 contacts ≈ 20 seconds. Operator pays only for contacts they actually want to outreach. |

## The 9-step pipeline (per brand)

### Step 1 — Identify target roles (M8.1: broad-keyword pool)
**Reads:** the brand's record in `brand_industry_map.json` (`typical_campaign_tier`, `headcount`, `revenue`, `company_stage`).

**M8.1 reshape:** The M8 5-category dicts (consumer-goods, b2b-saas, agency, media-entertainment, ecommerce) with ~6-8 narrow titles each are **replaced** by a single 12-keyword list:

```
marketing, brand, creator, influencer, partnerships, social,
growth, communications, PR, community, affiliate, founder
```

Apollo `/people/search` does substring matching against `person_titles`, so "marketing" catches every "X Marketing Y" variation; "brand" catches "Brand Manager", "Senior Brand Marketing"; "creator" catches "Director of Creator Economy", "Creator Partnerships Lead"; etc. This casts a much wider net than the M8 narrow lists at the same per-query cost (Apollo search is per-query, not per-record).

**The downstream filter is no longer the title list** — it's the Step 6 `outreach_recommendation` classifier (Phase B). The broad pool surfaces edge-case relevant titles + a tail of less-relevant titles; Phase B labels each row `recommended` / `not_recommended` / `requires_review` so the operator can filter to the contacts worth paying email-reveal cost on.

Callers can still supply `target_titles=[...]` to override the broad list (used by integration tests + niche agency workflows).

**Also pulled per-brand:** the brand's `creator_program_presence`. If `aspire`/`grin`/`ltk`/`shopmy` is listed, add "Creator Marketplace Lead" to targets. If `agency_of_record`, the talent's outreach goes via the AOR — add "Account Director at [AOR]" as a contact too.

**Output:** ordered list of target-title keywords (per-call override > broad list default).

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

### Step 5 — Email verification — REMOVED FROM PHASE A IN M8.1
**M8.1 reshape:** Phase A no longer pre-emptively reveals emails for every contact. Apollo `/people/search` returns no emails anyway, and we never call `/people/match` for the broad pool — that's the cost saving. Email reveal moves entirely to Step 5b, fired by the operator after reviewing the Phase B recommendations.

The strict honesty floor (Apollo `verified` / `catchall` only, no pattern-guessing) is preserved verbatim — it just applies per-row at Phase C reveal time instead of inline in Phase A.

### Step 5b — Bulk email reveal (M8.1 Phase C, operator-triggered)
**Trigger:** `POST /api/v1/brands/{brand_id}/contact-emails/reveal` with body `{contact_ids: [str]}`.

**Per contact_id:**
1. Look up the row + its `linkedin_url` + the brand's `domain`.
2. Fire `ApolloClient.match_person(linkedin_url=..., organization_domain=...)`. One HTTP call per contact; Apollo has no bulk endpoint; the global 60/min rate limit applies (20 contacts ≈ 20 seconds).
3. Apply the strict honesty floor: keep the returned email only if Apollo flagged it `verified` or `catchall`. Anything else → `email` stays null on the row.
4. Always set `revealed_at = now()` and record the actual `verification_status` (`verified` / `catchall` / `unverified` / `bounced` / `not_found` / `apollo_error`) so the UI shows "we tried" even when no usable email landed.

**Output:** the operator's selected contacts have their email + `verification_status` updated; `revealed_at` set on every reveal attempt. The Phase A pool of un-selected contacts stays with `email=null, revealed_at=null` — still visible in the inventory but not outreach-ready.

### Step 6 — Decision-role + outreach-recommendation classification (M8.1 dual call)
**Reads:** all contact records assembled so far + the brand's metadata (revenue, headcount, typical_campaign_tier, company_stage) + the contact's title + seniority.

**M8.1:** One batched Haiku call now returns TWO independent classifications per contact:

1. **`decision_role`** (existing): `buyer` / `influencer` / `gatekeeper` / `champion` / `unknown` — what role the contact plays in the buying decision.
2. **`outreach_recommendation`** (NEW): `recommended` / `not_recommended` / `requires_review` — should the operator pitch this contact directly. Distinct from decision_role: a CMO at a $50B brand is `influencer` (role) AND `not_recommended` (recommendation — too senior to engage with a creator pitch). An IM Manager anywhere is `buyer` + `recommended`.

The recommendation defaults to `requires_review` on any LLM error or invalid output — the system never auto-promotes a contact to `recommended` without an explicit LLM endorsement.

**Output:** each contact has `decision_role` + `decision_role_rationale` + `outreach_recommendation` + `outreach_recommendation_rationale` populated. Both rationales are one-sentence LLM-generated explanations the operator sees in the UI.

**LLM call** (Claude Haiku, single batched prompt per brand):

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

## M8 implementation notes (shipped vs deferred)

M8 v0.1 ships the **full 9-step pipeline** described above (Steps 2 → 3
→ 4 → 5 → 6 → 8 + qualification + policy filter) plus the REST surface
+ Celery task that fires the pipeline on a manual trigger. No schema
migration was required — the M1 ``brand_contact`` table + Pydantic
codegen + ``EncryptedString`` email column + the M3 Apollo / LinkedIn
vendor wrappers covered everything.

**Shipped:**

| Layer | Module / file |
|---|---|
| Step 2 — Apollo employee search | ``app/services/contact_enrichment/step_2_apollo_search.py`` |
| Step 3 — LinkedIn profile enrichment | ``app/services/contact_enrichment/step_3_linkedin_enrich.py`` |
| Step 4 — Exa + Claude web-search fallback | ``app/services/contact_enrichment/step_4_web_fallback.py`` |
| Step 5 — strict email-verification honesty floor | ``app/services/contact_enrichment/step_5_email_verify.py`` |
| Step 6 — Claude ``decision_role`` classifier (one batched call per run) | ``app/services/contact_enrichment/step_6_decision_role.py`` |
| Step 8 — dedupe + merge (linkedin > name+domain > email) | ``app/services/contact_enrichment/step_8_dedupe_merge.py`` |
| Qualification scoring | ``app/services/contact_enrichment/qualification.py`` |
| Policy filter (DNC + per-talent 14-day cooldown) | ``app/services/contact_enrichment/policy_filter.py`` |
| Orchestrator entry point | ``app/services/contact_enrichment/orchestrator.py`` |
| Atomic dual-write JSON snapshot | ``app/services/contact_enrichment/snapshot.py`` |
| Celery task | ``app/services/contact_enrichment_task.py`` |
| REST router (5 endpoints) | ``app/api/brand_contacts.py`` |

**Locked v0.1 decisions:**
- **Manual trigger only.** No auto-fire from M7's snapshot writer; users hit ``POST /api/v1/brands/{brand_id}/contact-enrichment/run`` themselves. Auto-trigger lands in M8.1 once we measure verified-email rate + cost-per-run on real brands.
- **Strict honesty floor on emails.** Step 5 keeps emails only when Apollo SMTP returns ``verified`` or ``catchall``. No pattern-guessing, no third-party verification (Hunter / NeverBounce). A brand with weak Apollo coverage may surface zero contacts — that's the right trade-off in v0.1.
- **Single batched LLM call for ``decision_role``.** Mirrors Search 13's pattern. Cap 12 candidates per brand keeps the prompt token-light. Falls back to ``unknown`` on any LLM error.

**Deferred to M8.1+:**
- Auto-trigger from M7's snapshot writer when ``brand_candidate.tier == "primary"`` AND ``qualification.tier ∈ {qualified, speculative}``.
- Champion-detection automation (Q7 above) — auto-set ``champion_for_talents`` from ``pitch_history`` where outcome ≥ ``meeting_booked``.
- Manual ``field_overrides[]`` layer (Q6) — currently every enrichment re-classifies; a user-flipped ``decision_role`` needs to survive without re-classification.
- AOR explicit handling (Q8).
- Paid email verification (Hunter / NeverBounce) — strict Apollo-only honesty floor in v0.1.
- Cross-talent contact-fatigue cap (Q5) — per-talent 14-day cooldown ships; the aggregate "max N contacts pitched per week per talent" cap defers to M9 where outreach-volume signal is real.
- Quarterly email re-verify cron + annual LinkedIn re-pull cron — v0.1 only records ``last_enriched_at`` and ``last_verified_at``; cadence decisions defer.

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
