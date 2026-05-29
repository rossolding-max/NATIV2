"""Search 18 — established brands discovered via Exa (M7.3).

Mirror of Search 15 but targets ESTABLISHED brands in the talent's
preferred industries — not just newly-funded ones. Search 15 catches
the up-and-coming startups; Search 18 catches the mid-to-large brands
that aren't in the 290-entry seed map yet (regional QSR chains,
non-top-of-mind apparel labels, niche home-improvement brands, etc.).

Same Exa + LLM extraction pipeline as Search 15. Geographic context
embedded in every query for higher hit-rate. Net-new brands surface as
candidates with ``search_tag="established_exa_discovery"`` and the
qualifier promotes them to ``tier="speculative"`` via the M7.3 emerging
branch when LLM confidence >= 0.70.

Cost guard: 6 query variations per industry, 5 industries per run, 5
results per query => ~150 Exa calls + ~30 Haiku extractions per run.
Run-level cap respected via ``settings.discovery_max_industries_per_run``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.discovery._brand_normalizer import find_canonical_seed_entry
from app.services.discovery._models import CandidateSource
from app.utils.logging import get_logger
from app.utils.slugify import slugify_brand_name

log = get_logger(__name__)


_SEARCH_TAG: str = "established_exa_discovery"
_BASE_WEIGHT: float = 0.20
_MAX_WEIGHT: float = 0.30

DEFAULT_MAX_INDUSTRIES: int = 5
DEFAULT_QUERIES_PER_INDUSTRY: int = 6
DEFAULT_RESULTS_PER_QUERY: int = 5


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _strip_json_fence(text: str) -> str:
    m = _JSON_FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _slugify(name: str) -> str:
    """Legacy alias — kept for callers; delegates to ``slugify_brand_name``."""
    return slugify_brand_name(name)


def _build_queries_for_industry(
    industry_id: str, *, talent_country: str | None = None
) -> list[str]:
    """Six query variations per industry, geo-embedded when available."""
    pretty = industry_id.replace("-", " ")
    geo = f" {talent_country}" if talent_country else ""
    return [
        f"top {pretty} brands{geo} 2026",
        f"best {pretty} brands for influencer marketing{geo}",
        f"{pretty} D2C brand directory{geo}",
        f"{pretty} brands creator program{geo}",
        f"established {pretty} brands instagram tiktok{geo}",
        f"{pretty} brands to watch{geo} 2026",
    ]


def _build_extraction_prompt(*, industry_id: str, raw_contents: list[dict[str, Any]]) -> str:
    """Compose the LLM prompt to extract established brand candidates."""
    blocks: list[str] = []
    for entry in raw_contents:
        url = entry.get("url") or ""
        title = entry.get("title") or ""
        body = (entry.get("text") or entry.get("content") or "")[:4000]
        blocks.append(f"--- {title} ({url}) ---\n{body}")
    pages = "\n\n".join(blocks) or "(no pages)"
    return (
        f"You are reviewing web pages about the {industry_id!r} industry, looking for "
        "ESTABLISHED brand names that operate creator marketing programs or are "
        "known to work with influencers.\n\n"
        "Rules:\n"
        '- Output JSON: {"brands": [{"brand_name": str, '
        '"suggested_industry_id": str, "confidence": float 0-1, '
        '"evidence": str (short quote), '
        '"source_url": str (the URL of the page above that mentions this brand), '
        '"domain": str | null (the brand\'s own website domain if visible, e.g. "lululemon.com"), '
        '"social_handles": {"instagram": str | null, "tiktok": str | null, '
        '"youtube": str | null, "x": str | null, "linkedin": str | null}}]}.\n'
        f"- Suggested industry MUST be the exact id {industry_id!r} unless the page "
        "makes clear the brand is in a different one.\n"
        "- ONLY include brands explicitly named in the page text — no generic mentions.\n"
        "- Prefer brands the page describes as well-known / popular / mainstream / "
        "leading. NEWLY FUNDED startups are out of scope here — Search 15 covers those.\n"
        "- Confidence 0.90+ = brand explicitly described as established / leading / "
        "well-known with examples; 0.70-0.89 = strong inference; below 0.70 = drop.\n"
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
        log.warning("search_18_llm_response_not_json", raw=raw[:200])
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
                if isinstance(value, str) and value.strip():
                    social_handles[platform] = value.strip()
                else:
                    social_handles[platform] = None
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


async def _exa_search_and_extract(
    *,
    industry_id: str,
    queries: list[str],
    results_per_query: int,
) -> list[dict[str, Any]]:
    """Run Exa searches + Claude extraction for one industry, per query.

    M7.5 — processes each query independently so every extracted brand
    can be tagged with the EXACT query that surfaced it, plus the
    title/url of the Exa result Claude attributed the mention to.
    """
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
                "search_18_exa_search_failed", industry=industry_id, query=query, error=str(exc)
            )
            continue

        raw_results = [r for r in (resp.get("results") or []) if isinstance(r, dict)]
        if not raw_results:
            continue

        result_by_url: dict[str, dict[str, Any]] = {
            (r.get("url") or ""): r for r in raw_results if r.get("url")
        }

        prompt = _build_extraction_prompt(industry_id=industry_id, raw_contents=raw_results)
        try:
            response = await client.messages.create(
                model=settings.anthropic_default_model,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            log.warning(
                "search_18_llm_failed", industry=industry_id, query=query, error=str(exc)
            )
            continue

        text_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", "") or "")
        parsed = _parse_llm_response(
            "".join(text_parts), fallback_industry_id=industry_id
        )

        for brand in parsed:
            url = brand.get("source_url") or ""
            matched = result_by_url.get(url)
            brand["source_url"] = url or None
            brand["source_title"] = (matched or {}).get("title") if matched else None
            brand["exa_query"] = query
            extracted.append(brand)

    return extracted


async def run(
    *,
    top_industry_ids: list[str],
    brand_industry_map: dict[str, Any],
    talent_country: str | None = None,
    max_industries: int = DEFAULT_MAX_INDUSTRIES,
    queries_per_industry: int = DEFAULT_QUERIES_PER_INDUSTRY,
    results_per_query: int = DEFAULT_RESULTS_PER_QUERY,
) -> list[CandidateSource]:
    """Run Search 18 across the top-N industries; return established net-new brands."""
    if not top_industry_ids:
        return []

    industries = list(dict.fromkeys(top_industry_ids))[:max_industries]

    raw_brands: list[Any] = brand_industry_map.get("brands") or []
    seed_brands: list[dict[str, Any]] = [e for e in raw_brands if isinstance(e, dict)]

    seen: set[tuple[str, str]] = set()  # (brand_id, exa_query)
    sources: list[CandidateSource] = []

    for industry_id in industries:
        queries = _build_queries_for_industry(industry_id, talent_country=talent_country)[
            :queries_per_industry
        ]
        extracted = await _exa_search_and_extract(
            industry_id=industry_id,
            queries=queries,
            results_per_query=results_per_query,
        )
        # M7.6 — fire 2-Exa-call enrichment for brands missing IG/TikTok.
        from app.services.discovery._social_enrichment import enrich_extracted_brands_inplace

        await enrich_extracted_brands_inplace(extracted, seed_brands)
        for cand in extracted:
            name = cand["brand_name"].strip()
            # M7.4 — canonicalise against the seed map so e.g.
            # "Ford Motor Company" lands on the canonical "Ford" brand_id
            # rather than emitting as a duplicate emerging-tier entry.
            canonical = find_canonical_seed_entry(name, seed_brands)
            if canonical is not None:
                canonical_name = canonical.get("name") or name
                brand_id = _slugify(canonical_name)
                emit_name = canonical_name
                emit_industry = canonical.get("industry_id") or cand["industry_id"]
                note_prefix = f"canonicalised from {name!r} | "
            else:
                brand_id = _slugify(name)
                emit_name = name
                emit_industry = cand["industry_id"]
                note_prefix = ""
            # M7.5 — dedup on (brand_id, exa_query) so each Exa query
            # that surfaced the brand emits its own provenance entry.
            dedup_key = (brand_id, cand.get("exa_query") or "")
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            confidence = cand["confidence"]
            weight = _BASE_WEIGHT + (_MAX_WEIGHT - _BASE_WEIGHT) * (confidence - 0.70) / 0.30
            weight = max(_BASE_WEIGHT, min(_MAX_WEIGHT, weight))
            evidence = (cand.get("evidence") or "")[:200]
            note = f"{note_prefix}llm_confidence={confidence:.2f} | {evidence}".rstrip(" |")
            sources.append(
                CandidateSource(
                    brand_id=brand_id,
                    brand_name=emit_name,
                    industry_id=emit_industry,
                    search_tag=_SEARCH_TAG,
                    weight=weight,
                    note=note[:240],
                    exa_query=cand.get("exa_query"),
                    exa_result_url=cand.get("source_url"),
                    exa_result_title=cand.get("source_title"),
                    brand_domain=cand.get("domain"),
                    brand_social_handles=cand.get("social_handles"),
                )
            )
            log.info(
                "search_18_brand_pending_writeback",
                brand_name=name,
                industry_id=cand["industry_id"],
                confidence=confidence,
            )
    return sources
