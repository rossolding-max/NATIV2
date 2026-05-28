"""Search 13 — values-aligned brand classifier (LLM-driven).

Given the talent's ``brand_preferences.values_red_lines`` (what they
will NOT work with) and ``values_aligned_themes`` (positive
preferences), runs ONE Claude call per discovery run that batches the
top N already-surfaced candidate brands and asks which align with the
talent's values.

This is a SECONDARY search: it boosts existing candidates rather than
discovering net-new ones. The orchestrator calls it AFTER the
deterministic + Exa searches have run so the candidate pool is real.

Weight: 0.05 — small additive boost. The signal is "this brand's
mission/category fits the talent's values" which is a soft, qualitative
match.

Cost: 1 LLM call per discovery run (capped at 50 candidate brands),
making it the cheapest LLM-driven search in the pipeline.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.discovery._models import CandidateSource
from app.utils.logging import get_logger

log = get_logger(__name__)


_SEARCH_TAG: str = "values_aligned"
_WEIGHT: float = 0.05
_MAX_CANDIDATES: int = 50


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _build_prompt(
    *,
    values_aligned_themes: list[str],
    values_red_lines: list[str],
    candidates: list[dict[str, Any]],
) -> str:
    aligned_block = "\n".join(f"  - {t}" for t in values_aligned_themes) or "  (none stated)"
    red_block = "\n".join(f"  - {t}" for t in values_red_lines) or "  (none stated)"
    cand_block = "\n".join(
        f"  - {c['brand_name']} (industry: {c['industry_id']})" for c in candidates
    )
    return f"""You are screening brand candidates for a talent agency.

The talent's stated VALUES (positive themes they want their sponsors to reflect):
{aligned_block}

The talent's RED LINES (industries / themes they refuse to associate with):
{red_block}

Below is a candidate brand list. For each, decide whether it ALIGNS with
the talent's positive values (NOT just "absence of red lines" — that's
the policy filter's job). Return ONLY the brands that have a positive
alignment.

Candidates:
{cand_block}

Respond with JSON ONLY in this exact format (no prose, no markdown
fences):
{{
  "aligned": [
    {{"brand_name": "...", "rationale": "one sentence"}}
  ]
}}
"""


def _parse_response(response_text: str) -> list[dict[str, Any]]:
    """Tolerantly parse the LLM response and return ``aligned`` list."""
    text = response_text.strip()
    # Strip code-fence wrappers if the model included them despite the prompt.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try the first {...} block.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    aligned = data.get("aligned") if isinstance(data, dict) else None
    if not isinstance(aligned, list):
        return []
    out: list[dict[str, Any]] = []
    for item in aligned:
        if not isinstance(item, dict):
            continue
        name = item.get("brand_name")
        rationale = item.get("rationale") or ""
        if isinstance(name, str) and name.strip():
            out.append({"brand_name": name.strip(), "rationale": str(rationale).strip()})
    return out


def _dedupe_candidate_pool(sources: list[CandidateSource], cap: int) -> list[dict[str, Any]]:
    """Collect distinct (brand_name, industry_id) from sources, capped at ``cap``."""
    seen: set[str] = set()
    pool: list[dict[str, Any]] = []
    # Order by source weight descending so the cap takes the strongest signals.
    ordered = sorted(sources, key=lambda s: s.weight, reverse=True)
    for s in ordered:
        key = s.brand_name.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        pool.append({"brand_name": s.brand_name, "industry_id": s.industry_id})
        if len(pool) >= cap:
            break
    return pool


async def run(
    *,
    brand_preferences: dict[str, Any],
    surfaced_sources: list[CandidateSource],
    brand_industry_map: dict[str, Any],
    max_candidates: int = _MAX_CANDIDATES,
) -> list[CandidateSource]:
    """Batch-classify which already-surfaced brands align with the talent's values."""
    values_aligned_themes = [
        t for t in (brand_preferences.get("values_aligned_themes") or []) if isinstance(t, str)
    ]
    values_red_lines = [
        t for t in (brand_preferences.get("values_red_lines") or []) if isinstance(t, str)
    ]
    if not values_aligned_themes and not values_red_lines:
        # No values context to align against.
        return []
    if not surfaced_sources:
        return []

    pool = _dedupe_candidate_pool(surfaced_sources, cap=max_candidates)
    if not pool:
        return []

    from app.agents.llm_client import get_async_anthropic
    from app.config import settings

    client = get_async_anthropic()
    prompt = _build_prompt(
        values_aligned_themes=values_aligned_themes,
        values_red_lines=values_red_lines,
        candidates=pool,
    )
    try:
        response = await client.messages.create(
            model=settings.anthropic_default_model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        log.warning("search_13_llm_failed", error=str(exc))
        return []

    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text_parts.append(getattr(block, "text", "") or "")
    aligned = _parse_response("".join(text_parts))
    if not aligned:
        return []

    # Build name -> entry index over the seed map so the source carries
    # the canonical brand_id + industry_id.
    brand_index: dict[str, dict[str, Any]] = {}
    for entry in brand_industry_map.get("brands") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str):
            brand_index[name.strip().lower()] = entry
        for alias in entry.get("aliases") or []:
            if isinstance(alias, str):
                brand_index[alias.strip().lower()] = entry

    sources: list[CandidateSource] = []
    seen: set[str] = set()
    for item in aligned:
        name = item["brand_name"]
        entry = brand_index.get(name.lower())
        if entry is None or not entry.get("industry_id"):
            continue
        brand_id = _slugify(entry["name"])
        if brand_id in seen:
            continue
        seen.add(brand_id)
        sources.append(
            CandidateSource(
                brand_id=brand_id,
                brand_name=entry["name"],
                industry_id=entry["industry_id"],
                search_tag=_SEARCH_TAG,
                weight=_WEIGHT,
                note=item["rationale"] or "LLM-classified as values-aligned.",
            )
        )
    return sources
