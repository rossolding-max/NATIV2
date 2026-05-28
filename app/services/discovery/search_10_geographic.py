"""Search 10 — geographic alignment.

For each country in ``talent.data.audience_demographics.top_countries[]``,
find brands whose ``hq_country`` matches OR whose ``sells_in_countries``
includes the country (or the canonical ``"global"`` sentinel). Surface
each match as a candidate.

Weight is lighter (0.04 base, 0.08 if HQ match) than industry-tier
searches because geographic alignment alone isn't a strong signal — it's
a tie-breaker on top of other matches.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.discovery._models import CandidateSource

_WEIGHT_HQ_MATCH: float = 0.08
_WEIGHT_SELLS_IN_MATCH: float = 0.04


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _audience_countries(audience_demographics: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    raw = audience_demographics.get("top_countries") or []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str):
            out.add(item.strip().upper())
        elif isinstance(item, dict):
            code = item.get("country") or item.get("code") or item.get("iso2")
            if isinstance(code, str):
                out.add(code.strip().upper())
    return out


def _brand_sells_in(brand_entry: dict[str, Any]) -> set[str]:
    raw = brand_entry.get("sells_in_countries")
    countries: set[str] = set()
    if isinstance(raw, str):
        countries.add(raw.strip().upper())
    elif isinstance(raw, list):
        for c in raw:
            if isinstance(c, str):
                countries.add(c.strip().upper())
    return countries


def run(
    *,
    audience_demographics: dict[str, Any],
    brand_industry_map: dict[str, Any],
) -> list[CandidateSource]:
    """Find brands whose HQ / sells-in geography matches the talent's audience."""
    talent_countries = _audience_countries(audience_demographics)
    if not talent_countries:
        return []

    brands = brand_industry_map.get("brands") or []
    if not isinstance(brands, list):
        return []

    seen: set[str] = set()
    sources: list[CandidateSource] = []
    for brand_entry in brands:
        if not isinstance(brand_entry, dict):
            continue
        industry_id = brand_entry.get("industry_id")
        if not industry_id:
            continue
        brand_name = brand_entry.get("name")
        if not isinstance(brand_name, str):
            continue
        brand_id = _slugify(brand_name)
        if brand_id in seen:
            continue

        hq = (brand_entry.get("hq_country") or "").strip().upper() or None
        sells_in = _brand_sells_in(brand_entry)
        weight: float | None = None
        note: str = ""
        if hq and hq in talent_countries:
            weight = _WEIGHT_HQ_MATCH
            note = f"Brand HQ in {hq}; talent audience covers {hq}."
        elif "GLOBAL" in {s.upper() for s in sells_in} or (
            sells_in & {c.upper() for c in talent_countries}
        ):
            weight = _WEIGHT_SELLS_IN_MATCH
            note = f"Brand sells in {sorted(sells_in & talent_countries) or ['global']}."
        if weight is None:
            continue
        seen.add(brand_id)
        sources.append(
            CandidateSource(
                brand_id=brand_id,
                brand_name=brand_name,
                industry_id=industry_id,
                search_tag="geographic_alignment",
                weight=weight,
                note=note,
            )
        )
    return sources
