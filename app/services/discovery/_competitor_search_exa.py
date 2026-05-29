"""M7.7 — Exa-based competitor search (replaces S3/S4's curated lookup).

Given a brand name, fires 2 Exa queries:

  - "competitors of {brand}"
  - "direct competitors {brand} {country}"

Sends results to Claude for extraction. Returns a list of competitor
brand dicts the orchestrator can wrap into CandidateSource records.

Why replace S3/S4? `data/brand_competitors.json` only covers ~290 hand-
curated brands. Kevin's 12 past brands surfaced only 2 competitors
(Hilton, Hyatt — both via Marriott) because the other 11 weren't in
the curated file. Exa fills the gap: DoorDash for Dunkin', Walgreens
for CVS, etc.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.utils.logging import get_logger

log = get_logger(__name__)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _strip_json_fence(text: str) -> str:
    m = _JSON_FENCE_RE.search(text)
    return m.group(1).strip() if m else text.strip()


def _build_queries(*, brand_name: str, talent_country: str | None) -> list[str]:
    geo = f" {talent_country}" if talent_country else ""
    return [
        f"competitors of {brand_name}",
        f"direct competitors {brand_name}{geo}",
    ]


def _build_prompt(*, brand_name: str, raw_contents: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for entry in raw_contents:
        url = entry.get("url") or ""
        title = entry.get("title") or ""
        body = (entry.get("text") or entry.get("content") or "")[:4000]
        blocks.append(f"--- {title} ({url}) ---\n{body}")
    pages = "\n\n".join(blocks) or "(no pages)"
    return (
        f"You are reviewing web pages discussing competitors of the brand {brand_name!r}.\n\n"
        "Rules:\n"
        '- Output JSON: {"competitors": [{"brand_name": str, '
        '"confidence": float 0-1, "evidence": str (short quote), '
        '"source_url": str (the URL of the page above that mentions this brand)}]}.\n'
        f"- ONLY include brand names the page text describes as competitors of {brand_name!r}.\n"
        "- Skip generic categories or industry mentions — specific brand names only.\n"
        "- Confidence 0.90+ = explicitly listed as a competitor; "
        "0.70-0.89 = strong inference; below 0.70 = drop.\n"
        "- source_url MUST be one of the page URLs shown above.\n"
        "- Return ONLY the JSON. No prose, no markdown fences.\n\n"
        f"PAGES:\n\n{pages}\n"
    )


def _parse_response(raw: str) -> list[dict[str, Any]]:
    try:
        body = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        log.warning("competitor_exa_llm_response_not_json", raw=raw[:200])
        return []
    items = body.get("competitors")
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in items:
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
                "confidence": float(confidence),
                "evidence": str(entry.get("evidence") or "")[:280],
                "source_url": str(entry.get("source_url") or "").strip() or None,
            }
        )
    return out


async def find_competitors(
    *,
    brand_name: str,
    talent_country: str | None = None,
    results_per_query: int = 5,
    exa_client: Any = None,
    llm_client: Any = None,
) -> list[dict[str, Any]]:
    """Run the 2-query Exa+Claude pass for one brand. Returns extracted competitors."""
    if not brand_name or not brand_name.strip():
        return []
    if exa_client is None:
        from app.vendors.exa import ExaClient

        exa_client = ExaClient()
    if llm_client is None:
        from app.agents.llm_client import get_async_anthropic

        llm_client = get_async_anthropic()

    out: list[dict[str, Any]] = []
    for query in _build_queries(brand_name=brand_name, talent_country=talent_country):
        try:
            resp = await exa_client.search(
                query,
                num_results=results_per_query,
                contents={"text": {"includeHtmlTags": False, "maxCharacters": 4000}},
            )
        except Exception as exc:
            log.warning(
                "competitor_exa_search_failed", brand=brand_name, query=query, error=str(exc)
            )
            continue
        raw_results = [r for r in (resp.get("results") or []) if isinstance(r, dict)]
        if not raw_results:
            continue
        prompt = _build_prompt(brand_name=brand_name, raw_contents=raw_results)
        try:
            from app.config import settings

            response = await llm_client.messages.create(
                model=settings.anthropic_default_model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            log.warning("competitor_exa_llm_failed", brand=brand_name, query=query, error=str(exc))
            continue
        text_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", "") or "")
        parsed = _parse_response("".join(text_parts))
        for p in parsed:
            p["exa_query"] = query
            out.append(p)
    return out
