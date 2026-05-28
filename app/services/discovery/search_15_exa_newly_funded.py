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

from app.services.discovery._models import CandidateSource
from app.utils.logging import get_logger

log = get_logger(__name__)


_SEARCH_TAG: str = "recently_funded"
_BASE_WEIGHT: float = 0.10
_MAX_WEIGHT: float = 0.15

# Cost-guard caps. Defaults are conservative; a smoke run with a single
# talent + ~5 industries x 2 queries x 5 results = ~50 Exa calls + ~50
# Claude calls. Override per-call via ``run(...)`` kwargs.
DEFAULT_MAX_INDUSTRIES: int = 3
DEFAULT_QUERIES_PER_INDUSTRY: int = 2
DEFAULT_RESULTS_PER_QUERY: int = 5


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _strip_json_fence(text: str) -> str:
    m = _JSON_FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _build_queries_for_industry(industry_id: str) -> list[str]:
    """Two complementary queries per industry — recent funding + new launch."""
    pretty = industry_id.replace("-", " ")
    return [
        f"{pretty} D2C brand newly funded 2026 Series A Series B",
        f"new {pretty} startup brand launch 2026",
    ]


def _build_extraction_prompt(*, industry_id: str, raw_contents: list[dict[str, Any]]) -> str:
    """Compose the LLM prompt to extract brand candidates from page text."""
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
        '"evidence": str (short quote)}]}.\n'
        f"- Suggested industry MUST be the exact id {industry_id!r} unless the page "
        "makes clear the brand is in a different one.\n"
        "- ONLY include brands explicitly named in the page text.\n"
        '- Skip generic mentions ("the apparel category", "streetwear startups"). '
        "Specific brand names only.\n"
        "- Confidence 0.90+ = brand explicitly described as funded/launched; "
        "0.70-0.89 = strong inference; below 0.70 = drop.\n"
        "- Return ONLY the JSON. No prose, no markdown fences.\n\n"
        f"PAGES:\n\n{pages}\n"
    )


def _parse_llm_response(raw: str, *, fallback_industry_id: str) -> list[dict[str, Any]]:
    """Parse the LLM JSON response into a list of brand candidate dicts."""
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
        out.append(
            {
                "brand_name": name.strip(),
                "industry_id": entry.get("suggested_industry_id") or fallback_industry_id,
                "confidence": float(confidence),
                "evidence": str(entry.get("evidence") or "")[:280],
            }
        )
    return out


async def _exa_search_and_extract(
    *,
    industry_id: str,
    queries: list[str],
    results_per_query: int,
) -> list[dict[str, Any]]:
    """Run the Exa searches + Claude extraction for one industry.

    Returns a list of brand-candidate dicts. Errors land as log warnings;
    the orchestrator's per-search try/except treats Search 15 as best-
    effort.
    """
    from app.vendors.exa import ExaClient

    exa = ExaClient()
    collected_contents: list[dict[str, Any]] = []
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
        for r in resp.get("results", []) or []:
            if isinstance(r, dict):
                collected_contents.append(r)

    if not collected_contents:
        return []

    from app.agents.llm_client import get_async_anthropic
    from app.config import settings

    client = get_async_anthropic()
    prompt = _build_extraction_prompt(industry_id=industry_id, raw_contents=collected_contents)
    try:
        response = await client.messages.create(
            model=settings.anthropic_default_model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        log.warning("search_15_llm_failed", industry=industry_id, error=str(exc))
        return []
    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text_parts.append(getattr(block, "text", "") or "")
    return _parse_llm_response("".join(text_parts), fallback_industry_id=industry_id)


async def run(
    *,
    top_industry_ids: list[str],
    brand_industry_map: dict[str, Any],
    max_industries: int = DEFAULT_MAX_INDUSTRIES,
    queries_per_industry: int = DEFAULT_QUERIES_PER_INDUSTRY,
    results_per_query: int = DEFAULT_RESULTS_PER_QUERY,
) -> list[CandidateSource]:
    """Run Search 15 across the top-N industries; return new-brand candidates.

    The orchestrator decides which industries are "top" — typically the
    industries that already surfaced in Search 5/6/7 (primary tier hits).
    """
    if not top_industry_ids:
        return []

    industries = list(dict.fromkeys(top_industry_ids))[:max_industries]

    # Build a lookup so we can skip brands already in the seed map.
    existing_brand_names: set[str] = set()
    raw_brands: list[Any] = brand_industry_map.get("brands") or []
    for entry in raw_brands:
        if isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str):
                existing_brand_names.add(name.strip().lower())
            for alias in entry.get("aliases") or []:
                if isinstance(alias, str):
                    existing_brand_names.add(alias.strip().lower())

    seen: set[str] = set()
    sources: list[CandidateSource] = []

    for industry_id in industries:
        queries = _build_queries_for_industry(industry_id)[:queries_per_industry]
        extracted = await _exa_search_and_extract(
            industry_id=industry_id,
            queries=queries,
            results_per_query=results_per_query,
        )
        for cand in extracted:
            name = cand["brand_name"].strip()
            name_lower = name.lower()
            if name_lower in existing_brand_names:
                # Already in seed map — not net-new; skip (search 5/6/7 handle these).
                continue
            brand_id = _slugify(name)
            if brand_id in seen:
                continue
            seen.add(brand_id)
            # Scale weight with confidence: 0.70 -> 0.10, 1.00 -> 0.15.
            confidence = cand["confidence"]
            weight = _BASE_WEIGHT + (_MAX_WEIGHT - _BASE_WEIGHT) * (confidence - 0.70) / 0.30
            weight = max(_BASE_WEIGHT, min(_MAX_WEIGHT, weight))
            sources.append(
                CandidateSource(
                    brand_id=brand_id,
                    brand_name=name,
                    industry_id=cand["industry_id"],
                    search_tag=_SEARCH_TAG,
                    weight=weight,
                    note=(cand.get("evidence") or "Exa-surfaced; awaiting enrichment.")[:240],
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
