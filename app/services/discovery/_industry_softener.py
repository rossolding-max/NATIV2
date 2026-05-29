"""M7.4 — LLM industry softener for the brand-discovery pipeline.

The deterministic `niche_industry_affinity.json` table hand-curates
which industries are relevant for a given niche. It's necessarily
incomplete — a dad-life creator might have plausible affinity to
`pet-care`, `home-improvement`, `family-travel` even when the
hand-curated table doesn't list them.

This module runs ONE Claude Haiku call per discovery run, given the
talent's context + the industries the deterministic pipeline already
chose, and asks Claude which additional industries / sub-industries
are worth adding. The result is filtered against the known industry
taxonomy so hallucinated ids are dropped silently.

Output is consumed by the orchestrator and fed into:
  - Search 5/6/7 (primary/secondary/tertiary affinity walks)
  - Search 8 (parent/sibling niche walk)
  - Search 15 (Exa-driven newly-funded)
  - Search 18 (Exa-driven established)

Cost: 1 Haiku call per run. Cheap.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.utils.logging import get_logger
from app.utils.taxonomies import Taxonomies

log = get_logger(__name__)


_MAX_SUGGESTIONS: int = 20


def _build_prompt(
    *,
    talent_data: dict[str, Any],
    current_industries: list[str],
    industry_catalogue: list[dict[str, Any]],
) -> str:
    niches = list(talent_data.get("content_niches") or [])
    location = (talent_data.get("location") or {}).get("country") or "unspecified"
    audience = talent_data.get("audience_demographics") or {}
    demo_summary = (
        ", ".join(
            f"{k}={v}"
            for k, v in audience.items()
            if isinstance(v, (str, int, float)) and k != "raw"
        )
        or "no oauth-derived audience yet"
    )

    current_block = ", ".join(current_industries) or "(none chosen yet)"
    catalogue_block = "\n".join(
        f"  - {entry['id']} (parent: {entry.get('parent') or 'top-level'})"
        for entry in industry_catalogue
    )

    return f"""You are augmenting a brand-discovery pipeline for an influencer marketing agency.

TALENT CONTEXT:
- Niches: {", ".join(niches) or "(none)"}
- Location: {location}
- Audience signals: {demo_summary}

INDUSTRIES ALREADY CHOSEN by the deterministic affinity pipeline:
{current_block}

THE FULL INDUSTRY CATALOGUE (only ids in this list are valid):
{catalogue_block}

QUESTION: which ADDITIONAL industries / sub-industries from the
catalogue above are worth adding to this talent's discovery scope?
Focus on plausible commercial affinities the deterministic table
might have missed. Return at MOST {_MAX_SUGGESTIONS} ids.

Do not repeat ids already chosen. Only use ids that appear in the
catalogue exactly. Return JSON ONLY (no prose, no markdown fences):
{{
  "additional_industries": [
    {{"id": "...", "rationale": "one sentence"}}
  ]
}}
"""


def _parse_response(response_text: str) -> list[str]:
    """Pull the list of suggested industry ids; tolerate malformed JSON."""
    text = response_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    additional = data.get("additional_industries") if isinstance(data, dict) else None
    if not isinstance(additional, list):
        return []
    out: list[str] = []
    for item in additional:
        if not isinstance(item, dict):
            continue
        industry_id = item.get("id")
        if isinstance(industry_id, str) and industry_id.strip():
            out.append(industry_id.strip())
    return out


async def run(
    *,
    talent_data: dict[str, Any],
    current_industries: list[str],
    taxonomies: Taxonomies,
    llm_client: Any = None,
) -> list[str]:
    """Return additional industry_ids suggested by the LLM softener.

    Returns ``[]`` when the softener is disabled (per
    ``settings.discovery_industry_softener_enabled``), the LLM call
    errors, or no valid suggestions come back.

    ``llm_client`` is for test injection — production passes None and
    the function constructs a client via ``get_async_anthropic``.
    """
    from app.config import settings

    if not settings.discovery_industry_softener_enabled:
        return []

    # `taxonomies.industries` is keyed by industry_id; we flatten it
    # into a list of dicts each with the id field present for the prompt.
    # The isinstance guard tolerates Mock-typed industry attrs in unit tests
    # where the value isn't a real dict.
    industry_catalogue: list[dict[str, Any]] = [
        {**node, "id": industry_id}
        for industry_id, node in (taxonomies.industries or {}).items()
        if isinstance(node, dict)  # pyright: ignore[reportUnnecessaryIsInstance]
    ]
    if not industry_catalogue:
        return []

    if llm_client is None:
        from app.agents.llm_client import get_async_anthropic

        llm_client = get_async_anthropic()

    prompt = _build_prompt(
        talent_data=talent_data,
        current_industries=current_industries,
        industry_catalogue=industry_catalogue,
    )
    try:
        response = await llm_client.messages.create(
            model=settings.anthropic_default_model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        log.warning("industry_softener_llm_failed", error=str(exc))
        return []

    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text_parts.append(getattr(block, "text", "") or "")
    suggestions = _parse_response("".join(text_parts))
    if not suggestions:
        return []

    # Whitelist: drop any ids not in the taxonomy + drop dupes against
    # the already-chosen list.
    valid_ids = {entry["id"] for entry in industry_catalogue if isinstance(entry.get("id"), str)}
    current_set = set(current_industries)
    filtered: list[str] = []
    seen: set[str] = set()
    rejected: list[str] = []
    for suggested in suggestions:
        if suggested in current_set:
            continue
        if suggested not in valid_ids:
            rejected.append(suggested)
            continue
        if suggested in seen:
            continue
        seen.add(suggested)
        filtered.append(suggested)
    if rejected:
        log.info("industry_softener_rejected_unknown_ids", rejected=rejected)
    return filtered[:_MAX_SUGGESTIONS]
