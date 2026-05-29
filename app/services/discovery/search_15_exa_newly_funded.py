"""Search 15 — newly-funded brands discovered via Exa + Claude.

For each of the top-N industries the talent's other searches already
identified, run a focused Exa search (e.g. ``"<industry> D2C brand
newly funded 2026"``), fetch contents, and ask Claude to extract a
clean JSON list of ``{brand_name, suggested_industry_id, confidence,
evidence}``.

Each extracted brand is bucketed via M5's ``resolve_industry`` (exact
match in the brand_industry_map, else Exa+LLM fallback). Brands not
already in the seed map become net-new CandidateSources weight 0.10-0.15
scaled by LLM confidence; the writeback to the seed map itself is
stubbed (logs intent — actual merge needs a review queue, deferred
to M7.1).

Cost guard: capped fan-out of top-N industries x queries x results so
a single run stays inside ``settings.llm_budget_per_pack_usd``.
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


_SEARCH_TAG: str = "recently_funded"
# M7.3 — bump from 0.10-0.15 to 0.20-0.30 scaled by LLM confidence so
# emerging brands clear the 0.10 noise floor without needing the
# qualification emerging-tier promotion. The promotion is still wired
# in qualification.py for defence-in-depth.
_BASE_WEIGHT: float = 0.20
_MAX_WEIGHT: float = 0.30

# Cost-guard caps. M7.3 bumps queries-per-industry from 2 to 7 and the
# per-run industry cap from 3 to 5 (via settings.discovery_max_industries_per_run).
# Smoke: 5 industries x 7 queries x 5 results = ~175 Exa calls + ~35
# Claude extractions per run. Override per-call via ``run(...)`` kwargs.
DEFAULT_MAX_INDUSTRIES: int = 5
DEFAULT_QUERIES_PER_INDUSTRY: int = 7
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
    """M7.3 — seven complementary query variations per industry.

    When the talent's country is known, embed it in every query for a
    higher-relevance hit-rate. Falls back to global queries when the
    country isn't available.
    """
    pretty = industry_id.replace("-", " ")
    geo = f" {talent_country}" if talent_country else ""
    return [
        f"newly funded{geo} {pretty} brand 2026",
        f"{pretty} startup{geo} Series A Series B 2026",
        f"emerging{geo} {pretty} brand creator marketing",
        f"new {pretty} D2C launch{geo} 2026",
        f"indie {pretty} brand{geo} instagram tiktok",
        f"{pretty} brands to watch{geo} 2026",
        f"{pretty} startup creator partnership{geo}",
    ]


def _build_extraction_prompt(*, industry_id: str, raw_contents: list[dict[str, Any]]) -> str:
    """Compose the LLM prompt to extract brand candidates from one query's
    page results. M7.5 — asks for ``source_url`` per brand so each
    extracted brand can be traced back to the Exa result that mentioned it.
    """
    blocks: list[str] = []
    for entry in raw_contents:
        url = entry.get("url") or ""
        title = entry.get("title") or ""
        body = (entry.get("text") or entry.get("content") or "")[:4000]
        blocks.append(f"--- {title} ({url}) ---\n{body}")
    pages = "\n\n".join(blocks) or "(no pages)"
    return (
        f"You are reviewing web pages about the {industry_id!r} industry, looking for "
        "BRAND names that are newly funded or newly launched.\n\n"
        "Rules:\n"
        '- Output JSON: {"brands": [{"brand_name": str, '
        '"suggested_industry_id": str, "confidence": float 0-1, '
        '"evidence": str (short quote), '
        '"source_url": str (the URL of the page above that mentions this brand), '
        '"domain": str | null (the brand\'s own website domain if visible, e.g. "kudos.com"), '
        '"social_handles": {"instagram": str | null, "tiktok": str | null, '
        '"youtube": str | null, "x": str | null, "linkedin": str | null}}]}.\n'
        f"- Suggested industry MUST be the exact id {industry_id!r} unless the page "
        "makes clear the brand is in a different one.\n"
        "- ONLY include brands explicitly named in the page text.\n"
        '- Skip generic mentions ("the apparel category", "streetwear startups"). '
        "Specific brand names only.\n"
        "- Confidence 0.90+ = brand explicitly described as funded/launched; "
        "0.70-0.89 = strong inference; below 0.70 = drop.\n"
        "- source_url MUST be one of the page URLs shown above; copy it exactly.\n"
        "- domain: just the host (e.g. 'brandname.com'); null if not mentioned.\n"
        "- social_handles: extract handles in the form '@brandname' or full URLs "
        "if visible in the page text. null per platform when absent. Do not guess.\n"
        "- Return ONLY the JSON. No prose, no markdown fences.\n\n"
        f"PAGES:\n\n{pages}\n"
    )


def _parse_llm_response(raw: str, *, fallback_industry_id: str) -> list[dict[str, Any]]:
    """Parse the LLM JSON response into a list of brand candidate dicts.

    M7.5 — extracts ``source_url`` (the page URL Claude attributed the
    brand mention to) so per-brand Exa provenance is preserved.
    """
    try:
        body = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        log.warning("search_15_llm_response_not_json", raw=raw[:200])
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

    Returns a list of brand-candidate dicts, each carrying:
      ``brand_name``, ``industry_id``, ``confidence``, ``evidence``,
      ``source_url``, ``source_title``, ``exa_query``.

    A brand surfaced by N different queries appears as N separate dicts
    (the orchestrator can dedupe; for provenance we keep them split).
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
                "search_15_exa_search_failed", industry=industry_id, query=query, error=str(exc)
            )
            continue

        raw_results = [r for r in (resp.get("results") or []) if isinstance(r, dict)]
        if not raw_results:
            continue

        # Index by URL so the LLM can attribute brands back to specific
        # results. Title also pulled through for provenance display.
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
                "search_15_llm_failed", industry=industry_id, query=query, error=str(exc)
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
    """Run Search 15 across the top-N industries; return new-brand candidates.

    The orchestrator decides which industries are "top" — typically the
    industries that already surfaced in Search 5/6/7 (primary tier hits).
    M7.3 — ``talent_country`` (ISO-3166 alpha-2) embeds geography into
    every Exa query for higher relevance; omit to fall back to global
    queries.
    """
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
            # M7.4 — canonicalise against the seed map via the brand
            # normalizer so "Ford Motor Company" matches existing "Ford"
            # and emits as an extra Exa signal on Ford rather than a net-new
            # emerging-tier candidate.
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
            # M7.5 — dedup on (brand_id, exa_query) so the same brand
            # surfaced by two different queries emits two sources (each
            # with its own provenance). Same query hitting the brand
            # twice still emits once.
            dedup_key = (brand_id, cand.get("exa_query") or "")
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            # M7.3 — scale weight 0.20 (conf 0.70) -> 0.30 (conf 1.00).
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
            # Writeback to brand_industry_map.json is a stub for v0.1 —
            # log the intent so M7.1 has a hook.
            log.info(
                "search_15_brand_pending_writeback",
                brand_name=name,
                industry_id=cand["industry_id"],
                confidence=confidence,
            )
    return sources
