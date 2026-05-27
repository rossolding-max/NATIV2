# Vendor & External-Data Roadmap

**Status:** Draft v0.1 (2026-05-26). Single source of truth for which external services the system depends on, what's confirmed for v0.1, and what's deferred to future versions with the criteria for adding each.

## Confirmed for v0.1

### Exa — semantic web search
**Role:** powers Search 15 (recently-funded / newly-visible brands) and any other AI-grounding search the orchestrator needs. Also used by the Brand Enrichment pipeline (Step 4 fallback in `docs/brand_enrichment_workflow.md`), the Contact Enrichment pipeline (Step 4 in `docs/contact_enrichment_workflow.md`), and the **Phase 4.5 Discovery Call Prep pipeline** (external research pass — recent brand campaigns, news, contact background, competitor landscape; see `docs/discovery_prep_workflow.md`).
**Why Exa:** purpose-built for AI-agent workflows. Neural + keyword hybrid; clean structured outputs; content extraction endpoint; "find similar URL" lets you seed with one trending brand page and pull lookalikes; better signal-per-query than general search APIs for discovery use cases.
**Endpoints we'll use:**
- `/search` — neural search with `category` + `livecrawl` + `text` content extraction
- `/findSimilar` — given one trending brand URL, return similar pages
- `/contents` — extract structured page content for LLM brand extraction
**Cost:** free tier covers initial development; paid scales linearly with query volume. Re-evaluate when monthly call volume passes the free quota.
**Env var:** `EXA_API_KEY`.

### Apollo.io — contact discovery (Phase 3 lead vendor)
**Role:** Primary source for `data/brand_contacts/{brand_id}.json` (see `docs/contact_enrichment_workflow.md`). Provides employee lookup by brand domain + role filters, SMTP-verified emails, LinkedIn URLs, location, tenure. Best coverage on US/EU B2B + mid-to-large D2C brands.
**Why Apollo over alternatives:** ~73M+ companies and ~275M+ contacts; inline email verification; reasonable per-record economics at our expected volume.
**Endpoints we'll use:**
- `/people/search` — query employees by org domain + title filters
- `/people/match` — enrich a known person record
- `/organizations/enrich` — get company-level metadata
**Cost:** $99–$500+/mo by volume; roughly $0.20–$0.50 per enriched contact at scale. Budget per-talent, per-discovery-run.
**Env var:** `APOLLO_API_KEY`.

### LinkedIn data via RapidAPI — contact verification + activity reads
**v0.1 provider (M3 decision):** **RapidAPI's "Real-Time LinkedIn Scraper API"** — host `linkedin-data-api.p.rapidapi.com`, accessed through the RapidAPI gateway. The official LinkedIn API is partner-gated (~$10-50k/yr) and cannot fetch third-party profiles, so the realistic v0.1 path is a public-data scraper. The class name in code is `LinkedInScraperClient` to make the data source unambiguous.
**Role:** Confirms Apollo data is fresh (Apollo lags 3–6 months on job changes), pulls last-activity dates for the `recent_linkedin_activity` qualification signal, and resolves brand domains → LinkedIn company pages. See `docs/contact_enrichment_workflow.md` Step 3.
**Auth:** two RapidAPI gateway headers: `x-rapidapi-key: <RAPIDAPI_KEY>` + `x-rapidapi-host: linkedin-data-api.p.rapidapi.com`.
**v0.1 endpoints implemented:**
- `GET /` — fetch person profile by LinkedIn URL.
- `GET /get-company-by-domain` — resolve domain → company profile + employee counts.
- `GET /get-profile-posts` — recent activity feed for outreach personalisation.
**Env var:** `RAPIDAPI_KEY`. Deprecated alias `LINKEDIN_API_KEY` is honoured at config-load time (M3 backfill) but will be removed at M5.
**Cost:** per RapidAPI subscription tier (Basic / Pro / Ultra / Mega). Tier choice depends on per-talent enrichment volume.
**Future RapidAPI vendors:** if we adopt more, the gateway boilerplate moves to `app/vendors/_rapidapi_client.py`; until then it's inlined in `linkedin.py`.
**v0.1 scope is enrichment only — NOT outreach.** Reading profile data + last-activity dates only. Sending LinkedIn messages / InMails / connection requests is **deferred to v2** — see `docs/outreach_workflow.md` § "Email-only in v0.1". When v2 ships LinkedIn-channel sending, we'll evaluate sender vendors (Sales Navigator API vs third-party platforms like Closely / Expandi / La Growth Machine) against LinkedIn's automation-policy enforcement.

### Phase 4.6 proposal pack — file parsing (v0.1 in-process)
**Role:** Phase 4.6 (`docs/proposal_pack_workflow.md`) lets the agent upload brand briefs, discovery call notes, transcripts, and reference material to augment proposal generation context. Each file is parsed to text + LLM-summarised in-process; no external vendor for v0.1.
**Libraries:**
- `pypdf` — PDF text extraction
- `python-docx` — Word (.docx) text extraction
- Built-in text/markdown reader for .txt + .md
**Why in-process:** simple file types, no auth needed, no vendor cost, fully deterministic. Audio transcription + image OCR are deferred to v2 (different vendor profile).
**Limits:** 25MB per file, 100MB total per deal in v0.1. Files exceeding the limit can be referenced via external URL (the `external_url` field on `context_artefact`).
**Env vars:** none.

### Phase 4.6 proposal pack — call transcript links (deferred — v2)
**Role:** v2 adds support for referencing external call-recording transcripts in the proposal context — agent pastes a URL to their Otter.ai / Fireflies.ai / Grain / Zoom transcript, system stores the reference but does NOT fetch the transcript content in v0.1.
**v2 evaluation candidates:** Otter.ai (~$17/mo, real-time transcription, API), Fireflies.ai ($10-19/mo, AI-summary built in, robust API), Grain ($15-45/mo, sales-focused with deal-level analytics, API), Zoom Cloud Recording (built into Zoom Business+, native transcript API).
**v2 trade-offs:** authentication patterns differ (OAuth vs API-key); transcript-quality differences for nuanced influencer-marketing language; per-meeting cost; whether we fetch transcript content (requires storage + parsing) or only store the URL as a reference (agent reads it externally).
**v0.1 placeholder:** schema field `context_artefact.parser: "external_transcript_link"` + `external_url` exist and accept manual URL paste; the LLM is informed of the link but cannot read it.
**Env vars when wired:** `OTTER_API_KEY` / `FIREFLIES_API_KEY` / `GRAIN_API_KEY` / `ZOOM_CLIENT_ID` (whichever is chosen).

### Phase 4.8 invoice — platform APIs for deliverable detection (v0.1)
**Role:** Phase 4.8 (`docs/invoice_workflow.md`) detects when contracted deliverables go live by polling the talent's connected platform accounts. Detection scores candidate posts against `posting_schedule[]` entries and surfaces matches to the agent for confirmation. v0.1 covers Instagram + TikTok via direct platform APIs. Other platforms (YouTube, LinkedIn, X, podcast, Substack) deferred to v2 via Phyllo (see below).
**APIs (v0.1):**
- **Meta Graph API** (Instagram Business accounts only): `GET /{ig-user-id}/media` for Reels + Feed Posts + Carousels; `GET /{ig-user-id}/stories` for Stories. Requires `instagram_basic` + `instagram_manage_insights` scopes. Webhooks supported (v2 migration target).
- **TikTok Display API**: `GET /v2/video/list/`. Requires `video.list` scope. Rate limit 100 calls/day per user (tight — guides cron cadence).
**Why direct (not Phyllo) in v0.1:** narrower platform surface in v0.1 (IG + TikTok cover most influencer partnerships); avoids per-creator monthly Phyllo cost; full control over rate-limit handling and matching logic. Tradeoff = ongoing maintenance of two API integrations.
**Polling cadence:** 15 min for IG Stories (24h ephemeral); 1 hour for everything else. Cron only polls deals in DELIVERY substages with unmatched `posting_schedule[]` entries.
**oAuth token storage:** per-talent tokens captured during Phase 1 onboarding platform connection step. Refresh handled by the orchestrator's auth layer.
**Env vars:** `META_APP_ID`, `META_APP_SECRET`, `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`.

### Phase 4.8 invoice — Phyllo unified API for other platforms (deferred — v2)
**Role:** v2 expands deliverable detection coverage to YouTube, LinkedIn, X, podcast, Substack via a single unified API. v0.1 = manual URL entry for these platforms (agent enters post URL after talent posts).
**Why Phyllo for v2:** maintaining 5+ additional direct API integrations (YouTube Data API + LinkedIn Marketing API + X API v2 + RSS parsers + Substack RSS) is engineering-heavy. Phyllo provides one auth flow, one API contract, handles platform breakage, supports webhooks for real-time detection.
**Phyllo evaluation notes:** per-creator monthly pricing (~$50-200/creator/mo depending on tier). Economics work if creator roster is small-medium; at scale, direct APIs may win. Re-evaluate at v2 build time.
**Alternative considered:** Modash (similar coverage; more analytics-focused). To re-evaluate at v2 build time.
**v0.1 placeholder:** schema field `posted_detection.method = "phyllo_auto"` exists; `talent.platforms[]` already captures handles for these platforms (for display + manual URL validation).
**Env var when wired:** `PHYLLO_API_KEY`.

### Phase 4.8 invoice — markdown → PDF rendering (v0.1 in-process)
**Role:** Phase 4.8 renders invoice composed markdown to PDF for agent send. Same renderer stack as contract pack: Puppeteer (headless Chromium) for v0.1 default; pandoc as alternate.
**Why no Word artefact:** invoices are PDF-only by convention. Agent edits happen pre-send via the orchestrator UI (which re-renders the PDF on each edit); no need for an editable Word intermediate.
**Env vars:** none.

### Phase 4.8 invoice — payment + accounting integrations (deferred — v2)
**Role:** v0.1 = manual payment tracking (agent sets `payment_received_at` + `payment_method` when funds confirmed; daily overdue cron notifies agent for follow-up). v2 = webhook-driven auto-population from accounting integrations.
**v2 vendor options:**
- **Stripe Invoices** — auto-send invoice via Stripe; `invoice.paid` webhook auto-populates `payment_received_at` + `payment_amount_received_usd` + `payment_reference`. Also enables `viewed_by_brand` state via `invoice.viewed` webhook.
- **Xero** — UK/global accounting integration; sync invoice + payment status both directions.
- **QuickBooks** — US accounting integration; same pattern.
- **Wave** — free tier for small agencies.
**Schema already shaped:** `invoice_pack.payment_state` has `external_invoice_id` + `payment_reference` + `agent_review.send_method` enum supporting `stripe_invoice_send` / `xero_send` / `quickbooks_send`. Webhook handlers populate on payment events.
**Env vars when wired:** `STRIPE_API_KEY` / `XERO_CLIENT_ID` / `QUICKBOOKS_CLIENT_ID` (already noted in Phase 4 vendor integrations row).

### Phase 4.7 contract pack — markdown → Word + PDF rendering (v0.1 in-process)
**Role:** Phase 4.7 (`docs/contract_pack_workflow.md`) generates contract drafts from talent-per markdown templates. Renders `composed_markdown` to three artefacts:
- `contract.md` — markdown source-of-truth (built-in writer)
- `contract.docx` — editable Word file (via `python-docx`)
- `contract.pdf` — read-only PDF (via Puppeteer headless Chromium OR pandoc)
**Why in-process:** same rationale as Phase 4.6 file parsing — simple, deterministic, no vendor cost, full control over output quality.
**Markdown → Word fidelity caveats:** python-docx handles paragraphs + bold/italic + headings cleanly; tables (deliverables, timeline) need explicit conversion logic; signature blocks rendered as literal placeholder text the agent fills before sending. Agent can edit the .docx output before sending.
**Markdown → PDF options:** v0.1 default is Puppeteer (consistent with other Phase 4.x renderers). pandoc as alternate if Puppeteer install adds too much weight in some deployment contexts.
**Env vars:** none.

### Phase 4 vendor integrations (deferred — v2)
**Role:** Phase 4 deal lifecycle (`docs/deal_lifecycle_workflow.md`) currently tracks contracts + invoices manually in v0.1 (PDF upload + dates). v2 adds API integrations for the high-friction operations:

| Concern | v2 vendor options |
|---|---|
| Contract e-sign | **DocuSign** (industry standard), **PandaDoc** (best for proposal-to-contract flow), **HelloSign** / Dropbox Sign (cheaper) |
| Invoicing | **Stripe Invoices** (also handles payment), **Xero** (UK + global accounting), **QuickBooks** (US accounting), **Wave** (free) |
| Payment confirmation | Webhook from any of the above auto-populates `deal.close.payment_received_at` |

Schema is already shaped to absorb: `deal.contract.e_sign_provider` + `e_sign_envelope_id`, `deal.close.invoice_provider` + `invoice_id`. v0.1 = `manual` for both; v2 swaps to vendor enum values + populates IDs from API. Env vars `DOCUSIGN_API_KEY`, `STRIPE_API_KEY`, `XERO_CLIENT_ID` etc. added when each vendor wires up.

### Smartlead.ai — outreach send + sequence backend (Phase 3b lead vendor)
**Role:** Powers the cold-outreach engine spec'd in `docs/outreach_workflow.md`. Our app generates per-step AI content (Claude on our side) and pushes it to Smartlead via API; Smartlead handles the agency's sending mailbox + warmup, send scheduling, open/click tracking, reply detection. Webhooks fire back to our app for kill-logic and analytics.
**Why Smartlead over alternatives:** API-first design — purpose-built for custom-app integration. Unlimited mailbox warmup included in base plan. Robust webhook support for the kill-on-reply logic. Per-mailbox economics align with our agency-sends-on-behalf model.
**Why NOT Resend** (initially considered): Resend's terms of service explicitly prohibit cold/unsolicited outreach — they're a transactional email API. Accounts running cold campaigns get suspended. Resend is purpose-built for password resets / receipts / login alerts, not outbound prospecting.
**Endpoints we'll use:**
- `POST /campaigns` — create campaign per (talent, template)
- `POST /campaigns/{id}/leads` — push enrolled contact + AI-generated content
- `POST /campaigns/{id}/pause` — kill on reply
- Webhooks: `email_sent`, `email_delivered`, `email_opened`, `email_clicked`, `email_replied`, `email_bounced`, `email_unsubscribed`
**Agency-level mailbox setup:** v0.1 uses ONE sending mailbox per agency (typically `{agent_first_name}@{agency_domain}`), set up in Phase 0 per `docs/agency_setup_workflow.md`. Single warmup cycle (2-4 weeks). All talent onboarding plugs into this pre-warmed mailbox — no per-talent warmup wait. v2 multi-agent rosters will add one mailbox per additional agent.
**Cost:** ~$94/mo Pro tier per active agency mailbox; $39/mo Basic for a single agent. Compared to per-talent pricing this is a major cost reduction — one mailbox serves the whole roster.
**Env var:** `SMARTLEAD_API_KEY`.

---

## Deferred to future versions

Each deferred vendor has the same template: what it unlocks, cost, when to add, what we do without it.

### ScrapeCreators — TikTok / Instagram / Threads / Pinterest signals for the `last30days` skill (Search 16)
- **Unlocks:** the visual-first half of `last30days`. With ScrapeCreators on, the skill captures momentum from TikTok virality, Instagram reels, Threads conversation, and Pinterest engagement. Without it, the skill still works on Reddit / X / YouTube / HN / Bluesky / Brave / GitHub.
- **Cost:** 100 free credits/month, then pay-as-you-go (rate varies by source).
- **When to add:** when the roster includes visual-first niches where IG/TikTok is the dominant platform — beauty, fashion, fitness, food, lifestyle. For tech / finance / gaming creators, the Reddit + X + YouTube + HN signal mix is enough.
- **Without it:** Search 16 still runs and still surfaces trending brands; it just under-weights visual-platform-native trends. Watch the synthesis quality for visual-niche talents and add ScrapeCreators if signal feels thin.
- **Env var:** `SCRAPECREATORS_API_KEY`.

### Owler — competitor graph maintenance
- **Unlocks:** ongoing, low-effort maintenance of `data/brand_competitors.json` via Owler's community-curated "top competitors" API.
- **Cost:** free tier (limited queries); Pro from ~$35/mo.
- **When to add:** when manual curation of `brand_competitors.json` becomes a noticeable maintenance burden — likely 6+ months in as the brand universe grows past ~500.
- **Without it:** we maintain `brand_competitors.json` manually for the top brands and rely on AI inference + writeback for novel brands the orchestrator encounters.
- **Use pattern when added:** quarterly enrichment job that diffs Owler's competitor sets against ours and proposes updates for human review (we keep `brand_competitors.json` authoritative).

### Modash *or* HypeAuditor brand database — bulk expansion of `brand_industry_map.json`
- **Unlocks:** searchable database of ~500k+ brands tagged by category + creator-marketing activity signal. Could grow `brand_industry_map.json` from 290 → 5,000+ brands in one bulk-import pass.
- **Cost:** $250–$300/mo for either platform. Bulk import only needs 1–3 months of subscription.
- **When to add:** when the limited size of `brand_industry_map.json` becomes a clear discovery bottleneck — i.e. when the orchestrator's "AI fallback" for unknown brands is firing for a meaningful share of pitches. **Highest-leverage single vendor add on this list.**
- **Without it:** the writeback loop from Searches 15 + 16 grows the map organically over time (a few new brands per discovery run). Slower but free.
- **Use pattern:** subscribe for 1 month; bulk-export brands per industry into a one-time enrichment script that merges into `brand_industry_map.json`; cancel subscription; refresh quarterly with the same playbook.

### Exploding Topics — pre-trend brand detection
- **Unlocks:** complement to `last30days` Search 16 with a brand-level rising-signal database that surfaces emerging brands earlier than social-listening can.
- **Cost:** $39 – $249/mo depending on tier.
- **When to add:** if Search 16 isn't catching emerging brands early enough (i.e. brands keep appearing on the trending list 2–3 months *after* they've already broken out).
- **Without it:** `last30days` plus Search 15 (Exa-driven funding search) handles momentum + funding signals respectively. Exploding Topics' value is the gap between those two — pre-trend, pre-funding.

### Tribe Dynamics — Earned Media Value (EMV) reports per category
- **Unlocks:** the gold-standard signal of which brands are actually winning at creator marketing right now, ranked per category.
- **Cost:** enterprise (agency pricing, not publicly listed; assume $$$$).
- **When to add:** when scaling beyond a 50-talent roster with a corresponding marketing-data budget.
- **Without it:** brand quality is inferred from our enriched `typical_campaign_tier` + `creator_program_presence` fields + multi-source candidate scoring. Coarser than EMV but works.

### SimilarWeb — audience-overlap competitive sets
- **Unlocks:** "audiences who visit brand X also visit brand Y" — true measured audience-overlap signal. The richest possible input for competitor mapping.
- **Cost:** enterprise (~$15k+/yr).
- **When to add:** realistically, when budget is significant. The signal is great but the price tag is large for what is essentially an enhancement to Search 3 / 14.
- **Without it:** `brand_competitors.json` captures the marketing-positioning view sufficiently; we lose the "people who buy X also buy Y" cross-category surprise factor.

### Statista — static industry rankings
- **Unlocks:** published "top 20 brands by revenue per category" reports.
- **Cost:** subscription, varies by access level.
- **When to add:** as an alternative path to the Modash/HypeAuditor bulk-import — if you want curated rankings rather than activity-based ones.
- **Without it:** Modash/HypeAuditor covers the same ground with better creator-marketing relevance.

### Product Hunt API — day-of brand launches
- **Unlocks:** newly-launched products / brands daily, before they appear in funding databases or social media.
- **Cost:** **free**.
- **When to add:** anytime — low-effort, highest value for tech-adjacent and consumer-app niches (SaaS, AI, productivity, dating apps, fintech).
- **Without it:** Search 15 catches them eventually via Exa search; Search 16 catches them once they trend. Product Hunt would catch them on day 1.
- **Use pattern:** daily polling job that filters new launches by talent-relevant categories and pipes hits into the candidates output with a `recently_launched` source tag.

### Crunchbase API — structured funding data (this is Search #17 in `brand_discovery.md`)
- **Unlocks:** the API-backed structured version of Search 15. Precise filters by funding stage / round / date; freshness within 24h; structured `total_raised`, `last_round_size`.
- **Cost:** API access is enterprise-tier only.
- **When to add:** only with significant budget; Exa covers the same need with looser structure but fine recall.
- **Without it:** Search 15 via Exa identifies recently-funded brands well enough; we lose the structured metadata (exact dollar amounts, round dates) but that's rarely needed for pitching decisions.

### Spate — beauty / fashion / wellness trend prediction
- **Unlocks:** vertical-specific trend prediction in beauty, fashion, wellness.
- **Cost:** mid-market SaaS.
- **When to add:** only if a meaningful share of the roster is in those three verticals; otherwise overhead-heavy for narrow coverage.
- **Without it:** `last30days` covers these niches at lower precision but acceptable depth.

### Glimpse — cross-category trend prediction
- **Unlocks:** similar shape to Exploding Topics, cross-category instead of beauty-specific.
- **Cost:** $30+/mo.
- **When to add:** as a cheaper alternative to Exploding Topics; only if you want a second trend-prediction signal.
- **Without it:** one trend-prediction tool (Exploding Topics or Glimpse) is enough; no need for both.

---

## Phase 3 vendors (outreach, not discovery)

Phase numbering across this codebase: **Phase 1** = Talent Profile, **Phase 2** = Brand Discovery (what this roadmap mainly serves), **Phase 3** = Outreach. Apollo + LinkedIn API are now in the v0.1 confirmed list above because the Contact Enrichment pipeline (`docs/contact_enrichment_workflow.md`) is the bridge between Phase 2 and Phase 3. The vendors below extend the Phase 3 stack.

### Hunter.io — Apollo alternative / parallel email-verification (v2)
- **Unlocks:** pattern-based email finder with strong domain-coverage breadth; catches contacts at smaller brands Apollo misses; more affordable for high-volume verification.
- **Cost:** $34–$349/mo depending on tier.
- **When to add (v2):** when Apollo coverage gaps become a clear bottleneck (i.e. >20% of primary-tier brands return 0 Apollo hits) or when monthly verification volume makes Apollo's per-record costs unattractive.
- **Without it:** Apollo handles primary coverage; web-search backup + pattern-inference handles long-tail.
- **Env var (when added):** `HUNTER_API_KEY`.

### Clay.com — multi-source orchestrator (v2)
- **Unlocks:** aggregates Apollo + Hunter + LinkedIn + Twitter + 50+ other sources under one API. Per-record pricing (~$0.10–$0.50 per enrichment) means you only pay for what you query.
- **Cost:** $149–$800+/mo by volume; per-credit pricing for spiky workloads.
- **When to add (v2):** when contact volume becomes unpredictable and we want a single integration instead of managing 3–4 separate vendor APIs.
- **Without it:** Apollo + LinkedIn + Exa cover the v0.1 use case directly.
- **Env var (when added):** `CLAY_API_KEY`.

### RocketReach — Apollo alternative (v2)
- **Unlocks:** different coverage profile from Apollo; particularly strong in EU markets and on contacts at non-US companies.
- **Cost:** $79–$249/mo per seat.
- **When to add (v2):** if Apollo's EU coverage proves thin (talent roster has many UK/EU-targeting creators).
- **Without it:** Apollo + LinkedIn API cover the v0.1 need at the cost of some EU-brand gaps.

### Hunter.io / RocketReach / Clay — quick comparison
- Briefly: these are competitive with Apollo on different price/coverage tradeoffs. Decide closer to v2 based on observed Apollo coverage gaps.

### Smartlead / Instantly / Outreach.io — outreach automation (Phase 3.5)
- Email sequencing, deliverability, reply detection. **Distinct from contact discovery** — these are the *next* phase (sending the email), not finding the address. Will be addressed in Phase 3.5 outreach workflow spec.

---

## Decision criteria for any future vendor add

Use these as a checklist before subscribing to anything on this list:

1. **What specific search or feature does this unlock that we can't do without it?** If the answer is "marginally better data for an existing search", defer.
2. **What's the cheapest way to get the same outcome?** Often the answer is "one-month subscription + bulk export + cancel" rather than ongoing API access.
3. **Does this need to run at request-time, or only periodically?** Periodic enrichments (quarterly / monthly bulk imports) are far cheaper than per-request API calls.
4. **Is there a free tier / open-source alternative?** Many vendors have free tiers adequate for sub-50-talent rosters.
5. **Does our existing data structure need changes to absorb the new signal?** If yes, factor in the engineering cost.

---

## Current env-var inventory

This is what the orchestrator will need configured by v0.1:

| Env var | Service | Required? |
|---|---|---|
| `EXA_API_KEY` | Exa search (Search 15 + enrichment fallbacks + Phase 4.5 discovery prep external research) | **Yes** |
| `ANTHROPIC_API_KEY` | Claude calls (classification, extraction, decision-role tagging, outreach generation, reply classification) | **Yes** |
| `APOLLO_API_KEY` | Apollo contact discovery (Phase 3a v0.1) | **Yes** (when Phase 3a enrichment runs) |
| `RAPIDAPI_KEY` | RapidAPI gateway key — LinkedIn data via "Real-Time LinkedIn Scraper API" (Phase 3a v0.1). Replaces deprecated `LINKEDIN_API_KEY`. | **Yes** (when Phase 3a enrichment runs) |
| `SMARTLEAD_API_KEY` | Smartlead outreach send + sequence backend (Phase 3b v0.1) | **Yes** (when Phase 3b outreach runs) |
| `META_APP_ID` + `META_APP_SECRET` | Meta Graph API for Phase 4.8 IG deliverable detection (oAuth flow; per-talent tokens stored in talent profile) | **Yes** (when Phase 4.8 detection runs for IG talent) |
| `TIKTOK_CLIENT_KEY` + `TIKTOK_CLIENT_SECRET` | TikTok Display API for Phase 4.8 TikTok deliverable detection (oAuth flow) | **Yes** (when Phase 4.8 detection runs for TikTok talent) |
| `SCRAPECREATORS_API_KEY` | TikTok/IG/Threads/Pinterest in `last30days` (Search 16) | No (deferred) |
| `OPENROUTER_API_KEY` | Perplexity Sonar fallback in `last30days` | No (deferred) |
| `OWLER_API_KEY` | Owler competitor maintenance | No (deferred) |
| `MODASH_API_KEY` *or* `HYPEAUDITOR_API_KEY` | Brand database bulk import | No (deferred) |
| `EXPLODING_TOPICS_API_KEY` | Pre-trend brand detection | No (deferred) |
| `PRODUCT_HUNT_DEVELOPER_TOKEN` | Daily launch feed | No (deferred — but free when added) |
| `HUNTER_API_KEY` | Hunter.io email verification (Phase 3a v2) | No (v2) |
| `CLAY_API_KEY` | Clay multi-source orchestrator (Phase 3a v2) | No (v2) |
| `DOCUSIGN_API_KEY` | Contract e-sign (Phase 4 v2) | No (v2) |
| `STRIPE_API_KEY` | Invoicing + payment confirmation (Phase 4 v2) | No (v2) |
| `XERO_CLIENT_ID` | Accounting integration (Phase 4 v2) | No (v2) |
| `PHYLLO_API_KEY` | Phyllo unified creator API for Phase 4.8 expansion to YouTube/LinkedIn/X/podcast/Substack detection | No (v2) |

This inventory is the source of truth — when adding a new vendor, append to this table.

---

## Open questions

1. **Eval strategy.** Before paying for any of the deferred vendors, set up an A/B compare: run Search 15 / 16 with and without the vendor for a sample of talents, measure deltas in candidate quality. Don't subscribe blind.
2. **Per-talent vendor budgets.** Should heavy users (e.g. agencies running 100+ talents) get a tier where premium vendors are enabled, while solo creators run on the free-tier stack only? Likely yes; bake into the pricing model.
3. **Vendor failover.** Exa has occasional outages. Should the orchestrator silently fall back to a secondary search provider (Brave) when Exa returns errors, or hard-fail and retry?
4. **Apollo vendor terms review.** Apollo contact data is licensed; usage terms should be read against our specific use case (outreach on behalf of named creator talent). Standard CAN-SPAM hygiene applies — see `docs/contact_enrichment_workflow.md` § "Outreach hygiene & vendor terms".
