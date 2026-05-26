# Vendor & External-Data Roadmap

**Status:** Draft v0.1 (2026-05-26). Single source of truth for which external services the system depends on, what's confirmed for v0.1, and what's deferred to future versions with the criteria for adding each.

## Confirmed for v0.1

### Exa — semantic web search
**Role:** powers Search 15 (recently-funded / newly-visible brands) and any other AI-grounding search the orchestrator needs.
**Why Exa:** purpose-built for AI-agent workflows. Neural + keyword hybrid; clean structured outputs; content extraction endpoint; "find similar URL" lets you seed with one trending brand page and pull lookalikes; better signal-per-query than general search APIs for discovery use cases.
**Endpoints we'll use:**
- `/search` — neural search with `category` + `livecrawl` + `text` content extraction
- `/findSimilar` — given one trending brand URL, return similar pages
- `/contents` — extract structured page content for LLM brand extraction
**Cost:** free tier covers initial development; paid scales linearly with query volume. Re-evaluate when monthly call volume passes the free quota.
**Env var:** `EXA_API_KEY`.

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

## Phase 2 vendors (outreach, not discovery)

These don't belong in Brand Discovery but are noted here so they're not forgotten when the outreach phase begins.

### Apollo.io — contact discovery for outreach
- **Unlocks:** verified email addresses for marketing / PR / partnerships / brand contacts at target brands. ~275M+ contact records, ~73M+ companies.
- **Cost:** $99 – $500+/mo by volume.
- **When to add:** **Phase 2** — the moment Brand Discovery hands a target brand to the outreach engine, Apollo is the first call.
- **Why NOT for competitor discovery:** Apollo's "similar companies" is algorithmic by industry + size + tech-stack. That doesn't capture marketing-positioning competitive sets (Tesla vs Rivian) any better than our curated `brand_competitors.json`. And Apollo skews B2B SaaS — D2C consumer brands like Gymshark or Liquid Death are thinly covered. Save it for outreach where it's best-in-class.

### Hunter.io / RocketReach / Clay — Apollo alternatives for contact discovery
- Briefly: these are competitive with Apollo on different price/coverage tradeoffs. Decide closer to Phase 2.

### Smartlead / Instantly / Outreach.io — outreach automation
- Email sequencing, deliverability, reply detection. Phase 2 concerns.

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
| `EXA_API_KEY` | Exa search (Search 15) | **Yes** |
| `ANTHROPIC_API_KEY` | Claude calls (Search 13 + brand extraction throughout) | **Yes** |
| `SCRAPECREATORS_API_KEY` | TikTok/IG/Threads/Pinterest in `last30days` (Search 16) | No (deferred) |
| `OPENROUTER_API_KEY` | Perplexity Sonar fallback in `last30days` | No (deferred) |
| `OWLER_API_KEY` | Owler competitor maintenance | No (deferred) |
| `MODASH_API_KEY` *or* `HYPEAUDITOR_API_KEY` | Brand database bulk import | No (deferred) |
| `EXPLODING_TOPICS_API_KEY` | Pre-trend brand detection | No (deferred) |
| `PRODUCT_HUNT_DEVELOPER_TOKEN` | Daily launch feed | No (deferred — but free when added) |
| `APOLLO_API_KEY` | Outreach contact discovery | No (Phase 2) |

This inventory is the source of truth — when adding a new vendor, append to this table.

---

## Open questions

1. **Eval strategy.** Before paying for any of the deferred vendors, set up an A/B compare: run Search 15 / 16 with and without the vendor for a sample of talents, measure deltas in candidate quality. Don't subscribe blind.
2. **Per-talent vendor budgets.** Should heavy users (e.g. agencies running 100+ talents) get a tier where premium vendors are enabled, while solo creators run on the free-tier stack only? Likely yes; bake into the pricing model.
3. **Vendor failover.** Exa has occasional outages. Should the orchestrator silently fall back to a secondary search provider (Brave) when Exa returns errors, or hard-fail and retry?
4. **GDPR / data-residency for Apollo.** Contact data has compliance implications in EU/UK markets that the rest of this stack doesn't. Worth a legal review before Phase 2 turns it on.
