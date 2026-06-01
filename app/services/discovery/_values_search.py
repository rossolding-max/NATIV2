"""M7.7 — Values-aligned Exa-driven discovery (S13 v2).

Given the talent's ``brand_preferences.values_aligned_themes[]`` AND a
list of approved industries (from Phase 1.5), fires per-themexper-industry
Exa queries like:

  - "sustainable activewear brands US"
  - "female-founded grocery brands US"
  - "BIPOC-owned beauty brands US"

The agency operator opts in: when values_aligned_themes is empty AND
no default themes are configured, this is a no-op.

Emits search_tag = "values_aligned_exa".
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


def _build_queries(*, themes: list[str], industry_id: str, talent_country: str | None) -> list[str]:
    pretty = industry_id.replace("-", " ")
    geo = f" {talent_country}" if talent_country else ""
    return [f"{theme} {pretty} brands{geo}" for theme in themes]


def _build_prompt(
    *, industry_id: str, themes: list[str], raw_contents: list[dict[str, Any]]
) -> str:
    blocks: list[str] = []
    for entry in raw_contents:
        url = entry.get("url") or ""
        title = entry.get("title") or ""
        body = (entry.get("text") or entry.get("content") or "")[:4000]
        blocks.append(f"--- {title} ({url}) ---\n{body}")
    pages = "\n\n".join(blocks) or "(no pages)"
    return (
        f"You are reviewing web pages about the {industry_id!r} industry, looking for "
        f"BRAND names that explicitly align with these talent values: {themes!r}.\n\n"
        "Rules:\n"
        '- Output JSON: {"brands": [{"brand_name": str, '
        '"suggested_industry_id": str, "confidence": float 0-1, '
        '"evidence": str (the values-aligned phrasing from the page), '
        '"source_url": str (one of the page URLs above), '
        '"themes_matched": [str, ...] (which of the input themes apply)}]}.\n'
        f"- ONLY include brands the page describes as aligning with the given themes "
        "(not generic 'sustainable category' mentions).\n"
        "- Confidence 0.90+ = brand explicitly described as aligned; "
        "0.70-0.89 = strong inference; below 0.70 = drop.\n"
        "- source_url MUST be one of the page URLs shown above.\n"
        "- Return ONLY the JSON. No prose, no markdown fences.\n\n"
        f"PAGES:\n\n{pages}\n"
    )


def _parse_response(raw: str, *, fallback_industry_id: str) -> list[dict[str, Any]]:
    try:
        body = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        log.warning("values_search_llm_response_not_json", raw=raw[:200])
        return []
    items = body.get("brands")
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
        themes_matched = entry.get("themes_matched") or []
        if isinstance(themes_matched, list):
            themes_matched = [t for t in themes_matched if isinstance(t, str)]
        else:
            themes_matched = []
        out.append(
            {
                "brand_name": name.strip(),
                "industry_id": entry.get("suggested_industry_id") or fallback_industry_id,
                "confidence": float(confidence),
                "evidence": str(entry.get("evidence") or "")[:280],
                "source_url": str(entry.get("source_url") or "").strip() or None,
                "themes_matched": themes_matched,
            }
        )
    return out


async def find_values_aligned_brands(
    *,
    themes: list[str],
    industries: list[str],
    talent_country: str | None = None,
    results_per_query: int = 5,
    exa_client: Any = None,
    llm_client: Any = None,
) -> list[dict[str, Any]]:
    """Run the Exa+Claude values-aligned search per (theme x industry).

    No-op when themes or industries is empty.
    """
    themes_filtered = [t.strip() for t in themes if t and t.strip()]
    if not themes_filtered or not industries:
        return []
    if exa_client is None:
        from app.vendors.exa import ExaClient

        exa_client = ExaClient()
    if llm_client is None:
        from app.agents.llm_client import get_async_anthropic

        llm_client = get_async_anthropic()

    out: list[dict[str, Any]] = []
    for industry_id in industries:
        for query in _build_queries(
            themes=themes_filtered,
            industry_id=industry_id,
            talent_country=talent_country,
        ):
            try:
                resp = await exa_client.search(
                    query,
                    num_results=results_per_query,
                    contents={"text": {"includeHtmlTags": False, "maxCharacters": 4000}},
                )
            except Exception as exc:
                log.warning(
                    "values_search_exa_failed",
                    industry=industry_id,
                    query=query,
                    error=str(exc),
                )
                continue
            raw_results = [r for r in (resp.get("results") or []) if isinstance(r, dict)]
            if not raw_results:
                continue
            prompt = _build_prompt(
                industry_id=industry_id, themes=themes_filtered, raw_contents=raw_results
            )
            try:
                from app.config import settings

                response = await llm_client.messages.create(
                    model=settings.anthropic_default_model,
                    max_tokens=1500,
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as exc:
                log.warning(
                    "values_search_llm_failed",
                    industry=industry_id,
                    query=query,
                    error=str(exc),
                )
                continue
            text_parts: list[str] = []
            for block in getattr(response, "content", []) or []:
                if getattr(block, "type", None) == "text":
                    text_parts.append(getattr(block, "text", "") or "")
            parsed = _parse_response("".join(text_parts), fallback_industry_id=industry_id)
            for p in parsed:
                p["exa_query"] = query
                out.append(p)
    return out
