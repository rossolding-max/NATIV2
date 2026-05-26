# NATIV2 — AI Influencer Marketing Assistant

## Goal

Build an AI-powered assistant that helps an influencer (or a roster of influencers) **find, connect with, and close deals with brands** to promote their products. The assistant should automate the manual grind of brand discovery, outreach, negotiation, and deal admin — while keeping the creator in control of voice, values, and final approvals.

## Phases

| # | Phase | Purpose |
|---|-------|---------|
| 1 | **Talent Profile** | Capture everything the system needs to know about the creator(s) — who they are, who their audience is, what they've done, what they cost, who they look like in the market. This is the foundation every later phase reads from. |
| 2 | _TBD_ | (To be defined by the user.) |
| 3 | _TBD_ | (To be defined by the user.) |

---

## Phase 1 — Talent Profile

### Output
A JSON file (`talents/*.json`) per talent, validated against `schemas/talent.schema.json`. The repo supports a **multi-talent roster** — one file per creator, or a combined roster file.

### Captured fields
- **Identity**: id, name, pronouns, age/DOB, location, timezone, languages, bio, content niches.
- **Contact**: direct email, manager/agency contact, phone (optional).
- **Billing entity**: company/legal name, country of operation, tax/VAT ID, preferred payment methods. _(Needed before any deal can be invoiced.)_
- **Platforms & handles**: per-platform handle, URL, follower count, engagement rate, avg views/likes/comments, and a **reference** to that platform's API key (e.g. `env:INSTAGRAM_TOKEN`) — never the raw secret.
- **Audience demographics**: age bands, gender split, top countries/cities, top languages, interests. Per-platform overrides supported.
- **Previous brand deals** (rich): brand name, industry, campaign date, platform, deliverables, fee (optional), usage rights granted, performance notes, brand contact.
- **Similar talent**: same shape as the main talent (id, name, handles, previous brands + industries) — used for competitive positioning and to seed brand discovery.
- **Rate card**: per platform → per deliverable type (e.g. Instagram → Reel / Story / Feed / Carousel / Live). Supports bundles, usage rights uplift %, exclusivity uplift %, whitelisting uplift %.
- **Brand preferences & restrictions**: preferred industries, blocked industries (e.g. gambling, alcohol), active exclusivities (with end date), values/red lines.
- **Working terms**: default usage rights (organic / whitelisting / paid social), default usage duration, content turnaround time, revisions included, blackout/availability dates.
- **Press kit & assets**: link to media kit, headshots, demo reels, notable press mentions, awards.
- **Disclosure defaults**: FTC/ASA disclosure style (`#ad`, `#sponsored`, etc.).
- **Other stats**: free-form key/value bag for anything that doesn't fit (e.g. newsletter subs, podcast downloads, Discord size).

### Added beyond the original brief
The fields below were not in the original request but were added because later phases (outreach, negotiation, contracts, invoicing) will fail without them:
- Billing entity / tax info.
- Per-platform follower count, engagement rate, avg views/likes/comments (live stats — needed for media-kit-style pitches).
- Brand preferences/restrictions and active exclusivities (so the assistant doesn't pitch a conflicting brand).
- Default usage rights, turnaround, revisions (so rate-card quotes are apples-to-apples).
- Disclosure defaults (compliance).
- Press kit URL and assets (so outreach emails can attach proof).
- Free-form `other_stats` bag for anything bespoke.

### Files
- `schemas/talent.schema.json` — JSON Schema (Draft 2020-12) describing the profile.
- `talents/example-talent.json` — template instance, partially filled.
- `data/niches.json` — canonical creator content-niche taxonomy.
- `data/industries.json` — canonical brand-industry taxonomy.
- `data/brand_industry_map.json` — seed lookup of well-known brand names → `industry_id`. Used by the app's auto-complete and grows over time.
- `.gitignore` — ensures any `*.local.json` or `.env` files containing real keys are never committed.

### Reference taxonomies
Both taxonomy files follow the same shape:
```jsonc
{
  "version": "1.0.0",
  "items": [
    { "id": "kebab-case-slug", "name": "Display Name", "parent": "parent-id-or-null", "aliases": ["search", "terms"] }
  ]
}
```
Top-level entries have `parent: null`; sub-entries reference their parent's `id`. `industries.json` additionally flags `sensitive: true` for categories that are commonly restricted on social platforms or require explicit creator opt-in (alcohol, gambling, tobacco, crypto, etc.).

### How the talent profile links to the taxonomies
The talent profile stores **only `id` slugs**, never display names — that way display labels, translations, and re-namings can change in the taxonomy files without touching any talent record.

| Profile field | References | Validated by |
|---|---|---|
| `content_niches[]` | `data/niches.json` `id` | Schema pattern (`#/$defs/nicheId`) + app load-time check against taxonomy |
| `previous_brands[].industry_id` | `data/industries.json` `id` | Schema pattern (`#/$defs/industryId`) + app load-time check |
| `brand_preferences.preferred_industries[]` | `data/industries.json` `id` | Same |
| `brand_preferences.blocked_industries[]` | `data/industries.json` `id` | Same |
| `brand_preferences.active_exclusivities[].industry_id` | `data/industries.json` `id` | Same |
| `similar_talent[].previous_brands[].industry_id` | `data/industries.json` `id` | Same |

JSON Schema validates the **slug format** (kebab-case). The app validates **slug membership** in the taxonomy on load, since JSON Schema can't dereference external JSON for `enum`.

### Auto-completing `industry_id` from a brand name
When the user types a brand into `previous_brands[].brand`, the app resolves `industry_id` automatically. Resolution order:

1. **Exact match** on `name` in `data/brand_industry_map.json` (case-insensitive).
2. **Alias match** on the `aliases[]` of each entry.
3. **Domain match** if the user pasted a URL or `@domain`.
4. **AI inference fallback** (later phase) — the assistant reads the brand's website / first-page search results and classifies it against `data/industries.json`. The result is then **written back** to `data/brand_industry_map.json` so future lookups are instant and the seed grows.

If multiple matches tie (rare), the app prefers the entry with the more specific (child) `industry_id` over a parent sector.
