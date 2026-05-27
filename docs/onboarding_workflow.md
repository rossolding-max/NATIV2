# Talent Onboarding Workflow

**Status:** Draft v0.1 (2026-05-26). Forward-looking spec — written before the app exists. Sits alongside `recommendation_algorithm.md` as the contract the app will implement.

## Goal

Take a user from zero to a **validated, complete `talents/{id}.json`** plus a seeded `similar_talent[]` array ready for AI enrichment. Semi-automated: pull what we can from APIs and media packs, ask only for what's still missing, and always show provenance so the user can trust the result.

## Principles

1. **Pull, don't ask** — every field we can fill from an API or extract from a media pack is auto-filled before the user is asked.
2. **Confirm before saving** — every auto-filled value carries `{value, source, confidence}` and the user reviews before commit.
3. **Progressive** — every step writes draft state; the user can quit and resume.
4. **Adaptive questionnaire** — only asks for what's missing or low-confidence after auto-fill.
5. **Honest about gaps** — at the end, surface a completeness score, not a fake-green "all done".

---

## Phases at a glance

| # | Phase | Time | Auto vs manual |
|---|---|---|---|
| 0 | Account creation | 30s | Manual (one-time) |
| 1 | Seed profile | 1–2 min | Manual (4 fields) |
| 2 | Platform connections | 2–5 min | Auto (OAuth) — paste fallback |
| 3 | Media pack extraction | 1–3 min upload + 30–90s processing | Auto (LLM vision) |
| 4 | Reconciliation review | 3–5 min | Manual confirm/edit |
| 5 | Guided questionnaire | 3–8 min | LLM-driven, adaptive |
| 6 | Brand history enrichment | 2–4 min | Auto + confirm |
| 7 | Similar-talent seeding + AI suggestions | 2–4 min | Hybrid |
| 8 | Final review + validation | 1–2 min | Manual confirm |
| 9 | AI research (background) | 5–30 min after save | Auto |

**Total user time: 15–25 minutes.** AI research in Step 9 runs after the user is done.

---

## Step 0 — Account creation

Standard sign-in. Email/SSO. Role selection: **Creator** (managing own profile) or **Manager/Agency** (managing a roster of talents). Skip on subsequent visits.

---

## Step 1 — Seed profile

The minimum required to create a draft record.

**Fields:**
- `name` (required)
- `primary platform` + handle (required) — used as the identity anchor for everything downstream
- `country` (required) — drives default billing entity, currency, timezone
- `content_niches[]` — pick up to 3 from a typeahead populated by `data/niches.json` (search by name + aliases)

**What happens behind the scenes:**
- `id` auto-derived as a slug from name (collision check; user can edit)
- `talents/{id}.draft.json` created with `status: draft`
- `timezone` defaulted from country
- `disclosure_defaults.style` defaulted by country (UK/EU → "Paid partnership"; US → "#ad")

**UX:** single screen, 4 inputs, "Continue" button.

---

## Step 2 — Platform connections

For each social platform, present a card:

```
┌────────────────────────────────────────┐
│ [IG]  Instagram                        │
│ Not connected                          │
│ [ Connect Instagram ]   |  use a token │
└────────────────────────────────────────┘
```

**OAuth-first per platform:**

| Platform | OAuth provider | Scopes needed | What we pull |
|---|---|---|---|
| Instagram | Meta Login for Business | `instagram_basic`, `instagram_manage_insights`, `pages_show_list` | followers, ER, avg likes/views/comments, audience age/gender/top countries/top cities |
| TikTok | TikTok for Developers Login Kit | `user.info.basic`, `video.list`, `video.insights` | followers, ER, avg views, follower demographics where available |
| YouTube | Google OAuth | `youtube.readonly`, `yt-analytics.readonly` | subscribers, avg views, watch time, demographics |
| Twitch | Twitch OAuth | `analytics:read:games`, `user:read:email` | followers, avg viewers, top games |
| LinkedIn | LinkedIn OAuth 2.0 | `r_organization_social`, `r_basicprofile` | followers, post engagement |
| Pinterest | Pinterest API v5 | `boards:read`, `pins:read`, `user_accounts:read` | followers, impressions, saves |
| Snapchat | Snap Kit | `display.snap_kit.user.external_id` | basic profile (limited insights) |

**Paste fallback** (collapsible "I have a token already" link):
- Token field, expiry date, scopes — for platforms without OAuth setup yet (X/Twitter limited tier, Substack, podcast hosts) or for users who already have tokens.

**Token storage — reference-only, two supported conventions** (per `schemas/talent.schema.json` § `access_token_ref`):
- **Dev / single-user:** `env:INSTAGRAM_TOKEN_<TALENT_ID>` — the orchestrator reads the value from environment variables. Simplest for development; no secret manager dependency.
- **Production / multi-tenant:** `vault:nativ2/instagram/<talent_id>` — the orchestrator dereferences via the configured secret manager (HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager, or equivalent).
- Never write the raw token to JSON. The `talents/{id}.json` file only ever stores the reference string.

### Outbound sender — handled by the agency, not per talent

Per the v0.1 architecture, outreach emails are sent by the talent's **agency** in the agent's name (e.g. `sarah@nativeagency.com`), not from per-talent mailboxes. The agency's sending mailbox + DNS records + 2-4 week warmup are a **one-time setup performed in Phase 0** — see `docs/agency_setup_workflow.md`. Talent onboarding does **not** require any DNS configuration or domain ownership.

What this means at this step: nothing. The talent's onboarding plugs into the agency's pre-warmed mailbox automatically. Outreach for this talent uses the agency's existing sender identity; no DNS records to add; no warmup wait per talent.

(In v2, when multi-agent rosters are supported, this step will gain an optional sub-step for routing the talent to a specific agent within the agency.)

**After each connection:**
1. Pull live stats → populate `platforms[N].stats` (followers, ER, avg views/likes/comments, `last_updated`).
2. Pull audience demographics → populate `audience_demographics` AND `platforms[N].audience_demographics_override` (per-platform values differ).
3. Re-bucket platform-native age bands to the IAB 13 bands the schema expects (Instagram exports its own bands; we round to nearest IAB segment).
4. Mark the platform card as `Connected — 285k followers, synced 2 min ago`.

**Stale handling:** on every login, if `last_updated > 7 days`, auto-refresh in background.

**Weekly background refresh:** independent of agent login, a weekly cron refreshes `talent.platforms[].stats.*` (followers, ER, avg views/likes/comments) for every active talent using the captured oAuth tokens. Same scopes as Phase 4.8 + 4.9 — no additional permissions. Keeps the talent profile's headline numbers fresh for discovery prep packs (Phase 4.5) + proposal packs (Phase 4.6) without depending on agent activity. If `stats.last_updated` falls behind by >14 days for a talent, the agent's morning summary flags it for manual reconnect.

**Token refresh:** long-lived where possible (Meta = 60d). On expiry, surface a "Reconnect" prompt; never silently lose data.

**Downstream validation — Phase 4.8 + 4.9 dependency:**

The oAuth scopes captured here are read again by:
- **Phase 4.8 deliverable detection cron** (`docs/invoice_workflow.md`): needs `instagram_basic` (list talent's media) + `instagram_manage_insights` (read insights) for IG; needs `video.list` for TikTok. Without these scopes, detection auto-matching falls back to manual URL entry for that platform.
- **Phase 4.9 KPI capture cron** (`docs/performance_report_workflow.md`): needs the same scopes plus `instagram_manage_insights` (for `/{ig-media-id}/insights` endpoint) and `video.insights` for TikTok. Without these, KPI snapshots in `deal.delivery.interim_kpi_snapshots[]` fall back to brand-reported or manual entry, and the performance report flags coverage gaps.

**Validation gate at end of Step 2:** for each platform the talent connected, the orchestrator tests one live API call against the connected token:
- **IG** → call `/me/media?fields=id&limit=1` (lightweight; tests `instagram_basic` + read access)
- **TikTok** → call `/v2/video/list/?fields=id&max_count=1` (tests `video.list`)
- **YouTube** → call `channels?part=id&mine=true` (tests `youtube.readonly`)

A platform with a connected token that fails the validation call gets badged `Limited — re-grant scopes to enable detection + KPI capture`. Talent can proceed; downstream pipelines fall back to manual entry but flag the gap.

---

## Step 3 — Media pack extraction

Dropzone accepts PDF / PPTX / PNG / JPG. Multi-file (creators often have separate rate card, bio deck, audience report).

**Pipeline:**
1. Files uploaded to temporary storage.
2. PDFs / PPTX rendered to page images.
3. Multimodal LLM (Claude with vision) processes each page, extracting:
   - **Bio** (1–3 sentences)
   - **Rate card** per platform per deliverable (Instagram Reel = £X; Story = £Y; etc.)
   - **Audience demographics** — age bands (re-bucketed to IAB), gender split, top countries, top cities, interests
   - **Past brand collaborations** — names + `industry_id` (Step 6 enrichment for unmapped brands)
   - **Brand-deal KPIs** — for each past brand, extract per Phase 1.5 (`docs/brand_deals_workflow.md`): campaign name, type, dates, deliverables, KPIs (reach / impressions / engagement / video metrics / conversions where visible), outcome, performance notes. Tagged per metric with `source: "platform_verified" | "brand_reported" | "self_reported"` based on what's quoted in the pack. Output goes to `data/brand_deals/{talent_id}.json` with `manually_verified_by_talent: false`, awaiting Step 4 reconciliation.
   - **Press mentions** — title, publication, date, URL if visible
   - **Awards / honours**
   - **Notable stats** — newsletter size, podcast downloads, anything in the "other_stats" bag
   - **Headshot images** — extracted and uploaded to asset storage
   - **Demo reel URLs** if mentioned
4. Every extraction returns `{value, confidence, source: "page 4, table top right"}`.

**Confidence routing:**
- `confidence ≥ 0.85` → auto-fill, tagged "Auto-filled, verify"
- `0.6 ≤ confidence < 0.85` → auto-fill, marked "Needs confirmation"
- `confidence < 0.6` → not filled; surfaced as a suggestion in Step 5 questionnaire

**UX:** progress bar during processing ("Reading page 4 of 12…"), then transitions to the reconciliation screen.

**Failure mode:** if extraction fails entirely (unreadable PDF, scan quality too low), skip — Step 5 will ask for the missing fields directly.

---

## Step 4 — Reconciliation review

A single review grid. Every field touched by Steps 2–3 appears with:

| Field | Value | Source | Conf. | Action |
|---|---|---|---|---|
| `bio` | "Lifestyle + fitness creator…" | Media pack p. 1 | 0.92 | ✏ Edit |
| `platforms[0].stats.followers` | 285,000 | Instagram API | 1.00 | (locked) |
| `audience_demographics.age_bands` | {25-29: 28, 30-34: 20, …} | Instagram API | 1.00 | (locked) |
| `rate_card.instagram.reel.price` | £4,000 | Media pack p. 5 | 0.88 | ✏ Edit |
| `previous_brands[2].brand` | "Gymshark" | Media pack p. 9 | 0.94 | ✏ Edit |

**Bulk actions:**
- `[ Accept all high-confidence (>0.85) ]`
- `[ Accept all ]`

**Conflicts** (e.g. Instagram API says 287k followers, media pack says 285k): show side-by-side, user picks one. Default favours the live API value.

**Output:** every reviewed field moves from auto-filled to confirmed. Edits update the value AND set `source = "user override"` so we don't try to re-extract on the next session.

---

## Step 5 — Guided questionnaire (adaptive)

LLM-driven, one question at a time. Asks only for:
- Fields **required by schema** that are still missing
- Fields **flagged as recommended for completeness** (rate card, working terms, brand prefs, contact)
- Fields that were **low-confidence in Step 3** and need user input

**Examples of branched questions:**

```
If rate_card is missing:
  "Do you have published rates? You can paste them, or I can
   suggest a starting range based on your 285k IG followers
   and 4.8% ER."
  → user pastes, accepts suggested ranges, or "skip for now"

If working_terms.default_usage_rights is missing:
  "What's your default for paid usage rights when a brand asks?"
  → [ Organic only / + Whitelisting (30d) / + Whitelisting (60d) / Full paid social ]

If brand_preferences.blocked_industries is missing:
  "Any industries you won't work with? Pick all that apply."
  → multi-select from sensitive-flagged categories in industries.json
   + free text

If billing_entity.legal_name is missing:
  "Are you invoicing under your own name or a company?"
  → branches to either personal or company sub-questions

If commission_override needed (talent has non-default agency split):
  "Standard agency commission is {agency_default_rate}%. Anything
   different for this talent?"
  → only shown if talent has a special commission arrangement
  → captures: commission_rate (decimal) + commission_model enum
   (agency_invoices_brand_pays_talent_net /
    talent_invoices_brand_agency_invoices_talent /
    talent_invoices_brand_talent_pays_agency)
  → defaults to absence (= use agency defaults)

If invoice_payment_override needed (talent routes payment to own account):
  "Where should brand payments for this talent's deals land? Agency
   defaults to {agency_payment_instructions_preview}. Override?"
  → captures: payment_instructions_markdown + preferred_payment_method
  → only relevant for commission_model = talent_invoices_brand_*

If active_exclusivities is missing:
  "Any current exclusivity deals that would block competing
   brands? E.g. 'exclusive with Nike in sportswear until Dec 2026'."
  → industry picker + brand name + end date

If brand_deals KPIs are missing or AI-extracted figures are flagged
low-confidence:
  "I extracted a Gymshark Q4 2025 campaign from your media pack but
   couldn't find verified KPIs. Can you share the numbers?"
  → guided form per deal: reach, engagement, video metrics, conversions
  → each metric has a "source" dropdown (platform_verified / brand_reported
    / self_reported) so the talent declares provenance honestly
  → "connect Instagram Insights" one-click pulls platform_verified figures
    for posts with URLs in deliverables[].post_urls
  → sets manually_verified_by_talent: true on save
```

**Skip-for-now is always allowed** on non-required fields. Skipped fields go into a "complete later" backlog visible from the dashboard.

**Progress indicator:** estimated remaining questions ("3 more questions to a complete profile"), based on how many recommended fields are still empty.

---

## Step 6 — Brand history enrichment

For each entry in `previous_brands[]`:

1. **Look up in `data/brand_industry_map.json`** (case-insensitive name, then aliases, then domain). If hit → `industry_id` auto-resolved, user confirms in a row.
2. **No match** → AI search:
   - Search the brand's website + top 3 search results.
   - LLM classifies against `data/industries.json`.
   - Suggest `industry_id` with confidence and reasoning.
3. **User confirms or overrides** the suggested `industry_id` (dropdown of all industries).
4. **On confirmation**, the inference is written back to `brand_industry_map.json` so the seed grows.

**UX:** table view of all previous brands, one row each:

```
Brand              | Industry            | Confidence | ✏
-------------------|---------------------|------------|---
Gymshark           | activewear          | seed       | ✓
Myprotein          | sports-nutrition    | seed       | ✓
Local Yoga Studio  | gyms-studios   ▼   | AI 0.78    | ✓
[ + Add brand ]
```

Same row also captures (optional): campaign date, deliverables, fee, usage rights granted, performance notes, brand contact — to bring the entry up to the full `brandDeal` shape.

---

## Step 7 — Similar talent seeding + AI suggestions

Two sub-steps.

### 7A — User seeds (manual)

"Who are your closest comparable creators? Add 3–5 names or handles."

For each entry:
- Name (required), platform handles (optional but recommended for AI research later)
- Creates a `similarTalent` record with `research.status = "seed"`, `previous_brands: []`, `inferred_niches: []`

UX: search-as-you-type field. If the name matches an existing creator in our internal directory (another managed talent or a previously-researched similar talent), pre-fill the handles and previous brands.

### 7B — AI suggests more

After ≥ 3 user seeds, an "AI suggested similar creators" panel appears:

```
Based on your niches (fitness, running, health-wellness) and your
audience demographics (25-39 female-skewed, GB/US), here are 8
creators you might consider comparable:

[ ] @anothercreator        — fitness + nutrition, 320k IG, 78% F
[ ] @runninggirl_uk        — running specialist, 180k IG, 71% F
[ ] @wellnesswithcat       — wellness + yoga, 410k IG, 82% F
[ ] @fitfounder            — fitness entrepreneur, 950k IG, 60% F
...

[ Accept selected ] [ Reject all ]
```

Each suggestion gets a one-line "why" so the user can judge fit at a glance. Suggestions sourced from:
- LLM knowledge of the creator scene (primary)
- Cross-reference with similar talents already in our system that share niches with this talent
- Optional: future integration with HypeAuditor / CreatorIQ / Modash discovery APIs

Accepted candidates become `similarTalent` seeds.

---

## Step 7.5 — Contract template + legal entity

Captures the per-talent contract template used by the Phase 4.7 contract pack pipeline (`docs/contract_pack_workflow.md`). This step is required before any deal can progress to CONTRACT stage for this talent.

**Inputs (mostly pre-populated from earlier steps):**
- `billing_entity.legal_name` / `country` / `tax_id` / `address` — from Step 5
- `working_terms.default_usage_rights` / `default_usage_duration_days` / `revisions_included` — from Step 5
- Talent's preferred governing law + jurisdiction — captured here if not already
- Optional: external legal reviewer identity (if talent uses outside counsel)

**Captured this step (into `talent.contract_template`):**
- `markdown_source` — the contract template text. Two paths:
  - **Starter template adoption** (recommended for v0.1): agency provides curated starter templates in `data/contract_template_starters/` (e.g. activewear default, CPG default, podcast read default). Onboarding flow lists starters; talent picks one; system copies into `markdown_source` for editing. `based_on_starter_template_id` records provenance.
  - **From scratch / upload existing**: talent (or talent's lawyer) pastes/uploads their preferred template. Markdown ideal; .docx accepted and converted.
- `merge_field_definitions[]` — declared by the starter template OR derived by scanning `markdown_source` for `{{...}}` patterns. UI shows each field with its expected source; talent confirms or remaps.
- `clause_applicability_rules[]` — pre-populated from starter; talent can add/edit. Each rule has plain-language condition + `default_decision` enum (include / exclude / llm_decide).
- `narrative_placeholders[]` — pre-populated from starter; tone guidance editable.
- `default_governing_law` + `default_jurisdiction` — common defaults: 'England and Wales' / 'State of California' / etc. UI offers preset list + freeform.
- `legal_reviewer_id` (optional) — if talent uses external counsel, capture their identity here. Defaults absent → falls back to assigned agent at gate time.
- `template_version` + `template_updated_at` — set automatically on save.

**Validation:**
- Every `{{merge_field}}` in `markdown_source` must have a matching entry in `merge_field_definitions[]` (or be flagged for agent to declare).
- Every `{{#if clause_id}}...{{/if}}` block must have a matching `clause_applicability_rules[].clause_id` (or be flagged).
- Every `{{narrative_*}}` placeholder must have a matching `narrative_placeholders[].placeholder` (or be flagged).
- Test compose: run a dry-run compose against placeholder context to confirm template renders without unresolved placeholders.

**Output:** `talent.contract_template` block fully populated. Deal contract pack generation can now fire for any deal involving this talent.

**Skip option:** for early-stage agencies still building out their first template, this step can be deferred (talent profile saves without `contract_template`). Deals can progress through LEAD + PROPOSAL stages but block at `contract_drafting` substage with an explicit "Talent contract template not yet configured" message.

### Contract template version bump enforcement (GAP-08 fix)

`talent.contract_template.template_version + .template_updated_at` track the lifecycle of the talent's adopted contract template. Every generated `contract_pack` snapshots the template_version it was generated against (`contract_pack.context_snapshot.template_version_used`) for legal audit trail.

**Enforcement requirement:** the API layer MUST bump `template_version` + set `template_updated_at = now()` on ANY modification to:

- `talent.contract_template.markdown_source`
- `talent.contract_template.merge_field_definitions`
- `talent.contract_template.clause_applicability_rules`
- `talent.contract_template.narrative_placeholders`
- `talent.contract_template.default_governing_law`
- `talent.contract_template.default_jurisdiction`

`legal_reviewer_id` is exempt — changing the reviewer doesn't change the contract's terms.

**Implementation:** either DB-level trigger or service-layer guard. Never trust callers to manually bump. Format suggestion: semver (e.g. `1.0.0` → `1.0.1` for narrative tone tweak; `1.1.0` for new conditional clause added; `2.0.0` for full markdown rewrite). API endpoints MUST reject updates that change these fields without an accompanying version bump (or auto-bump server-side).

**Why this matters MORE than the invoice template (GAP-07):** contracts are legal instruments. If a dispute arises, the signed contract's exact clause set must be reproducible from the captured `template_version_used`. Without enforcement, audit trail fails — a major compliance + liability exposure.

**Failure mode if skipped:** silent drift between captured template_version strings + actual template content; surfaces only during legal dispute / audit when reconstruction fails.

**Cross-deal interaction:** if talent updates their template (legitimate version bump) mid-deal, existing contract_packs in flight stay anchored to the prior version (via context_snapshot). New contract_packs for the same deal would use the new version. This is intentional — the audit captures what was generated when, not what currently exists.

---

## Step 8 — Final review + validation

Full schema validation runs against `schemas/talent.schema.json`. Two outcomes:

**A. Validation passes**
- Profile completeness score: e.g. "92% complete — missing: optional `press_kit.media_kit_url`, optional manager contact"
- `[ Save profile ]` button finalises `talents/{id}.json`, status flips from `draft` → `active`
- Confirmation page with: download as JSON, share preview link, "Start onboarding another talent" (for agency users)

**B. Validation fails**
- Highlight problematic fields inline with the failure message
- "Fix and continue" button per field

---

## Step 9 — AI research + Brand Discovery kickoff (background, after save)

Two parallel background jobs trigger automatically on profile save:

### 9A — Similar-talent enrichment
For each `similarTalent` with `research.status = "seed"`:

1. Set `research.status = "researching"`.
2. AI scrapes/searches public sources (their handles, press, recent #ad posts) to find recent brand collaborations.
3. For each found brand name → resolve `industry_id` via `brand_industry_map.json` (with AI fallback).
4. Populate `previous_brands[]` with `{brand, industry_id, source: "<source URL>"}`.
5. Run the **inversion algorithm** (per `docs/recommendation_algorithm.md` § Similar-talent inversion) to back-derive `inferred_niches[]` from the brand list.
6. Update `research.status = "enriched"`, `research.last_researched_at = now`, `research.sources = [...]`.
7. Notify the user (in-app badge / email if opted in).

**Failure path:** `research.status = "failed"` with a reason; user can manually fill the record or retry.

**Refresh cadence:** after 90 days, status flips to `stale`; user is prompted to refresh.

### 9B — Brand Discovery first run
The orchestrator immediately triggers a full **Brand Discovery** run for the new talent — runs all 16 searches per `docs/brand_discovery.md` and writes the first `data/brand_candidates/current/{talent_id}.json`. Two sequencing notes:
- Searches 2 and 4 (similar-talent-driven) wait for Step 9A to complete first, then re-run as a delta — without similar-talent enrichment they'd surface nothing.
- All other searches run immediately on whatever talent-profile fields are populated; they don't block on AI research.

User is notified when the first candidate list is ready (typically within 5–10 minutes of save). After this initial run, the standard monthly cron and on-profile-update triggers from `docs/brand_discovery.md` take over.

---

## State machine

```
TALENT PROFILE:
  draft  ───────▶  active  ───────▶  archived
                     │
                     └──▶ active (re-confirmed quarterly)

SIMILAR TALENT RESEARCH:
  seed  ──▶  researching  ──▶  enriched  ──(90d)──▶  stale  ──┐
                  │                                              │
                  └──▶  failed                                   │
                          │                                      │
                          └────────── manual retry ──────────────┘
```

---

## Data populated per step (cumulative)

| Step | Fields populated |
|---|---|
| 1 Seed | `id`, `name`, `location.country`, `timezone`, `disclosure_defaults.style`, `platforms[0].platform`, `platforms[0].handle`, `content_niches[]` |
| 2 Platforms | `platforms[].url`, `.primary`, `.stats.*`, `.api_credentials.access_token_ref`; `audience_demographics.*` (per-platform overrides too) |
| 3 Media pack | `bio`, `rate_card.*`, `previous_brands[].brand`, `press_kit.media_kit_url`, `press_kit.headshot_urls`, `press_kit.press_mentions`, `press_kit.awards`, `other_stats.*`, supplements `audience_demographics.*` |
| 4 Reconciliation | confirms/edits everything from 2–3 |
| 5 Questionnaire | `pronouns`, `age` / `date_of_birth`, `languages`, `contact.*`, `billing_entity.*`, `working_terms.*`, `brand_preferences.*`, `disclosure_defaults.notes`, `commission_override.*` (if non-default), `invoice_payment_override.*` (if talent routes payment to own account), any rate-card gaps |
| 6 Brand enrichment | `previous_brands[].industry_id`, `.campaign_date`, `.deliverables`, `.fee`, `.usage_rights_granted`, `.performance_notes`, `.brand_contact` |
| 7 Similar talent | `similar_talent[].id`, `.name`, `.handles[]`, `.research.status` |
| 7.5 Contract template | `contract_template.markdown_source`, `.merge_field_definitions[]`, `.clause_applicability_rules[]`, `.narrative_placeholders[]`, `.default_governing_law`, `.default_jurisdiction`, `.legal_reviewer_id`, `.template_version`, `.based_on_starter_template_id` |
| 8 Validation | (no new fields — commits everything) |
| 9 AI research | `similar_talent[].previous_brands[]`, `.inferred_niches[]`, `.research.status`, `.research.last_researched_at`, `.research.sources` |

---

## Failure handling

| Failure | Fallback |
|---|---|
| OAuth flow fails / cancelled | Offer paste-fallback on the same card |
| Token revoked between sessions | Show "Reconnect" prompt; keep last-good data |
| Media pack extraction yields nothing | Skip; Step 5 questionnaire asks for the missing fields manually |
| Brand-industry AI inference fails | User picks from dropdown manually |
| AI similar-talent suggestions return empty | Skip suggestion panel; user can add more manually anytime |
| Schema validation fails at Step 8 | Inline error per field; "Fix and continue" |
| AI background research fails | `research.status = failed` with reason; manual edit + retry available |

---

## Save & resume

- Every step writes draft state to backend on transition.
- User can quit anytime; dashboard shows "Resume onboarding — last step: Reconciliation review".
- Drafts older than 30 days surface a "Still working on this?" prompt; after 90 days, archived (but not deleted).

---

## What this workflow does NOT cover (yet)

- **Bulk import** for agencies — CSV/spreadsheet template, JSON import from another system. Likely a "Step 1 alternative" in v0.2.
- **Internationalisation** — questionnaire is English-only at draft.
- **Privacy/consent screen** — explicit consent for storing audience demos and platform tokens; should be added as a Step 1.5.
- **Role-based access** for agencies — who can edit a talent profile after onboarding? Manager-only? Talent themselves? Needs a permissions model.
- **Live web research during questionnaire** — could enrich the LLM's questions with real-time data ("I see you were just featured in Vogue last week — should we add that to press mentions?"). Nice-to-have, not in v0.1.

---

## Open questions for v0.2

1. **Re-onboarding cadence.** When should we prompt the user to refresh the whole profile? Rate cards drift, audience demos shift, exclusivities expire. Quarterly nudge? Auto-detect significant changes?
2. **Trust signals on extracted data.** Should we show extraction provenance permanently on the dashboard, or only during onboarding?
3. **AI suggestion quality measurement.** When the user rejects a suggested similar talent, do we capture the reason ("wrong audience" / "not a competitor" / "I don't know them") to improve future suggestions?
4. **Approval gate before AI research kickoff.** Step 9 starts automatically — should the user explicitly opt in per similar-talent before AI scrapes their data?
5. **Platforms beyond the OAuth list.** Substack, podcast hosts, Discord, BookTok-specific platforms — how do we add them in priority order?
