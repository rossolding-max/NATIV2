"""M7.7 Phase 2 — Build the brand universe via Exa across 3 categories.

For each approved industry (no cap), fires three Exa+Claude extraction
families with geography embedded in every query:

  - Emerging  → newly funded / Series A-B / < 5 years old.   tag: exa_emerging
  - Growth    → Series C+ / regional leaders / mid-market.   tag: exa_growth
  - Established → mainstream / household-name / market leader. tag: exa_established

Three categories close the gap that emerged + established alone leave
(mid-market regional players like Wegmans, 5-15-year Series C+ DTCs).

Cost shape (per industry, per category): 7 Exa queries x 5 results +
1 Claude extraction per query = 35 Exa calls + 7 Haiku calls. With
3 categories that's ~120 Exa calls + 21 Haiku calls per industry.
Kevin's 80 approved industries → ~9,600 Exa calls + ~1,700 Haiku calls
≈ $50-60 per Phase 2 run + ~$10 for social enrichment.

The agency operator capped the industry count at Phase 1.5 — Phase 2
has no internal cap.
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from app.services.discovery._brand_normalizer import find_canonical_seed_entry
from app.services.discovery._industry_taxonomy import derive_top_level_and_sub_industry
from app.services.discovery._models import CandidateSource
from app.services.discovery._social_enrichment import enrich_extracted_brands_inplace
from app.utils.logging import get_logger
from app.utils.slugify import slugify_brand_name

log = get_logger(__name__)


# ── Category → tag + weight + queries ─────────────────────────────


BrandCategory = Literal["emerging", "growth", "established"]

_CATEGORY_TAG: dict[BrandCategory, str] = {
    "emerging": "exa_emerging",
    "growth": "exa_growth",
    "established": "exa_established",
}

_BASE_WEIGHT: float = 0.20
_MAX_WEIGHT: float = 0.30
_DEFAULT_RESULTS_PER_QUERY: int = 5


def _build_queries(
    *,
    category: BrandCategory,
    industry_id: str,
    talent_country: str | None,
) -> list[str]:
    """Per-category query templates with geography embedded."""
    pretty = industry_id.replace("-", " ")
    geo = f" {talent_country}" if talent_country else ""
    if category == "emerging":
        return [
            f"newly funded{geo} {pretty} brand 2026",
            f"{pretty} startup{geo} Series A Series B 2026",
            f"emerging{geo} {pretty} brand creator marketing",
            f"new {pretty} D2C launch{geo} 2026",
            f"indie {pretty} brand{geo} instagram tiktok",
            f"{pretty} brands to watch{geo} 2026",
            f"{pretty} startup creator partnership{geo}",
        ]
    if category == "growth":
        return [
            f"leading{geo} {pretty} brand 2026 Series C",
            f"fast-growing private {pretty} companies{geo}",
            f"{pretty} regional chains{geo}",
            f"{pretty} mid-market brands creator marketing",
            f"{pretty} brands 100+ employees{geo}",
            f"{pretty} brands $50M+ revenue{geo}",
            f"established direct-to-consumer {pretty}{geo}",
        ]
    # established
    return [
        f"top{geo} {pretty} brands 2026",
        f"best {pretty} brands for influencer marketing{geo}",
        f"{geo} {pretty} D2C brand directory".strip(),
        f"{pretty} brands creator program{geo}",
        f"established {pretty} brands instagram tiktok",
        f"top {pretty} brands to watch{geo} 2026",
    ]


# ── LLM extraction prompt + parser ────────────────────────────────


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _strip_json_fence(text: str) -> str:
    m = _JSON_FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _category_focus_clause(category: BrandCategory) -> str:
    if category == "emerging":
        return (
            "looking for BRAND names that are newly funded, newly launched, "
            "or Series A/B-stage (< 5 years old)."
        )
    if category == "growth":
        return (
            "looking for mid-market or growth-stage BRAND names: "
            "Series C and later, regional/national leaders, fast-growing "
            "private companies (typically 5-15 years old, $50M+ revenue or "
            "100+ employees). NOT household-name megabrands; NOT newly funded "
            "startups — both of those are out of scope here."
        )
    return (
        "looking for ESTABLISHED brand names that are mainstream, well-known, "
        "or household names that operate creator marketing programs. "
        "NEWLY FUNDED startups are out of scope."
    )


def _build_extraction_prompt(
    *,
    industry_id: str,
    category: BrandCategory,
    raw_contents: list[dict[str, Any]],
) -> str:
    blocks: list[str] = []
    for entry in raw_contents:
        url = entry.get("url") or ""
        title = entry.get("title") or ""
        body = (entry.get("text") or entry.get("content") or "")[:4000]
        blocks.append(f"--- {title} ({url}) ---\n{body}")
    pages = "\n\n".join(blocks) or "(no pages)"
    return (
        f"You are reviewing web pages about the {industry_id!r} industry, "
        f"{_category_focus_clause(category)}\n\n"
        "Rules:\n"
        '- Output JSON: {"brands": [{"brand_name": str, '
        '"suggested_industry_id": str, "confidence": float 0-1, '
        '"evidence": str (short quote), '
        '"source_url": str (the URL of the page above that mentions this brand), '
        '"domain": str | null (the brand\'s own website domain if visible, e.g. "kudos.com"), '
        '"social_handles": {"instagram": str | null, "tiktok": str | null, '
        '"youtube": str | null, "x": str | null, "linkedin": str | null}}]}.\n'
        f"- Suggested industry MUST be the exact id {industry_id!r} unless the "
        "page makes clear the brand is in a different one.\n"
        "- ONLY include brands explicitly named in the page text.\n"
        '- Skip generic mentions ("the apparel category", "streetwear startups"). '
        "Specific brand names only.\n"
        "- Confidence 0.90+ = brand explicitly described as fitting this category; "
        "0.70-0.89 = strong inference; below 0.70 = drop.\n"
        "- source_url MUST be one of the page URLs shown above; copy it exactly.\n"
        "- domain: just the host (e.g. 'brandname.com'); null if not mentioned.\n"
        "- social_handles: extract handles in the form '@brandname' or full URLs "
        "if visible in the page text. null per platform when absent. Do not guess.\n"
        "- Return ONLY the JSON. No prose, no markdown fences.\n\n"
        f"PAGES:\n\n{pages}\n"
    )


def _parse_llm_response(raw: str, *, fallback_industry_id: str) -> list[dict[str, Any]]:
    try:
        body = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        log.warning("phase_2_llm_response_not_json", raw=raw[:200])
        return []
    raw_brands = body.get("brands")
    if not isinstance(raw_brands, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw_brands:
        if not isinstance(entry, dict):
            continue
        name = entry.get("brand_name")
        confidence = entry.get("confidence")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(confidence, int | float) or confidence < 0.70:
            continue
        social_raw = entry.get("social_handles") or {}
        social_handles: dict[str, str | None] = {}
        if isinstance(social_raw, dict):
            for platform in ("instagram", "tiktok", "youtube", "x", "linkedin"):
                value = social_raw.get(platform)
                social_handles[platform] = (
                    value.strip() if isinstance(value, str) and value.strip() else None
                )
        out.append(
            {
                "brand_name": name.strip(),
                "industry_id": entry.get("suggested_industry_id") or fallback_industry_id,
                "confidence": float(confidence),
                "evidence": str(entry.get("evidence") or "")[:280],
                "source_url": str(entry.get("source_url") or "").strip() or None,
                "domain": str(entry.get("domain") or "").strip() or None,
                "social_handles": social_handles or None,
            }
        )
    return out


# ── Exa fan-out per category x per industry ───────────────────────


async def _exa_extract_per_query(
    *,
    category: BrandCategory,
    industry_id: str,
    queries: list[str],
    results_per_query: int,
) -> list[dict[str, Any]]:
    """Run one Exa+Claude pass per query so each extracted brand carries
    its originating query string (M7.5 per-query provenance pattern)."""
    from app.agents.llm_client import get_async_anthropic
    from app.config import settings
    from app.vendors.exa import ExaClient

    exa = ExaClient()
    client = get_async_anthropic()
    extracted: list[dict[str, Any]] = []

    for query in queries:
        try:
            resp = await exa.search(
                query,
                num_results=results_per_query,
                category="company",
                contents={"text": {"includeHtmlTags": False, "maxCharacters": 4000}},
            )
        except Exception as exc:
            log.warning(
                "phase_2_exa_search_failed",
                industry=industry_id,
                category=category,
                query=query,
                error=str(exc),
            )
            continue

        raw_results = [r for r in (resp.get("results") or []) if isinstance(r, dict)]
        if not raw_results:
            continue

        result_by_url: dict[str, dict[str, Any]] = {
            (r.get("url") or ""): r for r in raw_results if r.get("url")
        }

        prompt = _build_extraction_prompt(
            industry_id=industry_id, category=category, raw_contents=raw_results
        )
        try:
            response = await client.messages.create(
                model=settings.anthropic_default_model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            log.warning(
                "phase_2_llm_failed",
                industry=industry_id,
                category=category,
                query=query,
                error=str(exc),
            )
            continue

        text_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", "") or "")
        parsed = _parse_llm_response("".join(text_parts), fallback_industry_id=industry_id)

        for brand in parsed:
            url = brand.get("source_url") or ""
            matched = result_by_url.get(url)
            brand["source_url"] = url or None
            brand["source_title"] = (matched or {}).get("title") if matched else None
            brand["exa_query"] = query
            brand["category"] = category
            extracted.append(brand)

    return extracted


# ── Public entry ──────────────────────────────────────────────────


async def run(
    *,
    approved_industries: list[str],
    brand_industry_map: dict[str, Any],
    taxonomies: Any,
    talent_country: str | None = None,
    categories: list[BrandCategory] | None = None,
    results_per_query: int = _DEFAULT_RESULTS_PER_QUERY,
) -> list[CandidateSource]:
    """Run Phase 2 across approved industries x categories.

    No internal cap on industries. The agency operator controlled scope at
    Phase 1.5 — Phase 2 trusts that.

    Returns a flat list of CandidateSource records ready for the
    orchestrator's merge step. Each source carries the M7.5 provenance
    (exa_query, exa_result_url, exa_result_title) AND M7.7 brand
    metadata (brand_domain, brand_social_handles, sub_industry on the
    industry_id field — split into top-level + sub at the QualifiedCandidate
    aggregation step in the orchestrator).
    """
    if not approved_industries:
        return []
    if categories is None:
        from app.config import settings as _settings

        categories = ["emerging", "established"]
        if _settings.discovery_growth_enabled:
            categories.insert(1, "growth")

    raw_brands: list[Any] = brand_industry_map.get("brands") or []
    seed_brands: list[dict[str, Any]] = [e for e in raw_brands if isinstance(e, dict)]

    seen: set[tuple[str, str, str]] = set()  # (brand_id, exa_query, category)
    sources: list[CandidateSource] = []

    for industry_id in approved_industries:
        for category in categories:
            queries = _build_queries(
                category=category, industry_id=industry_id, talent_country=talent_country
            )
            extracted = await _exa_extract_per_query(
                category=category,
                industry_id=industry_id,
                queries=queries,
                results_per_query=results_per_query,
            )
            # Social enrichment per category x industry; only brands missing
            # IG/TikTok get 2 follow-up Exa calls (M7.6 helper).
            await enrich_extracted_brands_inplace(extracted, seed_brands)

            for cand in extracted:
                name = cand["brand_name"].strip()
                canonical = find_canonical_seed_entry(name, seed_brands)
                if canonical is not None:
                    canonical_name = canonical.get("name") or name
                    brand_id = slugify_brand_name(canonical_name)
                    emit_name = canonical_name
                    emit_industry = canonical.get("industry_id") or cand["industry_id"]
                    note_prefix = f"canonicalised from {name!r} | "
                else:
                    brand_id = slugify_brand_name(name)
                    emit_name = name
                    emit_industry = cand["industry_id"]
                    note_prefix = ""

                dedup_key = (brand_id, cand.get("exa_query") or "", category)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                # Derive top-level + sub-industry now so the orchestrator
                # can aggregate them onto the candidate.
                top_level, sub = derive_top_level_and_sub_industry(emit_industry, taxonomies)

                confidence = cand["confidence"]
                weight = _BASE_WEIGHT + (_MAX_WEIGHT - _BASE_WEIGHT) * (confidence - 0.70) / 0.30
                weight = max(_BASE_WEIGHT, min(_MAX_WEIGHT, weight))
                evidence = (cand.get("evidence") or "")[:200]
                note = (
                    f"{note_prefix}category={category} | llm_confidence={confidence:.2f} | "
                    f"top_level_industry={top_level!r} | sub_industry={sub!r} | {evidence}"
                ).rstrip(" |")[:380]
                sources.append(
                    CandidateSource(
                        brand_id=brand_id,
                        brand_name=emit_name,
                        industry_id=emit_industry,
                        search_tag=_CATEGORY_TAG[category],
                        weight=weight,
                        note=note,
                        exa_query=cand.get("exa_query"),
                        exa_result_url=cand.get("source_url"),
                        exa_result_title=cand.get("source_title"),
                        brand_domain=cand.get("domain"),
                        brand_social_handles=cand.get("social_handles"),
                    )
                )

    return sources
