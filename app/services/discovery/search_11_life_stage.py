"""Search 11 — audience life-stage signal.

For the dominant age band of the talent's audience, surface brands in
the life-stage-aligned industries. v0.1 uses an inline mapping table
(IAB-derived); a richer per-band industry-weight matrix lands in M7.2.

Low base weight (0.04) — life-stage alignment alone is a weak signal,
but stacks usefully on top of niche / demographic matches.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.discovery._models import CandidateSource

_SEARCH_TAG: str = "life_stage_signal"
_WEIGHT: float = 0.04

# Inline life-stage -> industry map. Derived from IAB Purchase Intent
# segments per age cohort; v0.1 sticks with the broad strokes.
_LIFE_STAGE_INDUSTRIES: dict[str, list[str]] = {
    "13-17": ["gaming", "fashion-streetwear", "beauty-personal-care"],
    "18-24": ["gaming", "fashion-streetwear", "activewear", "specialty-retail"],
    "25-34": [
        "d2c-subscription",
        "wellness",
        "supplements-brands",
        "femtech",
        "telehealth",
        "specialty-retail",
    ],
    "35-44": [
        "parenting-products",
        "home-furnishing",
        "real-estate",
        "personal-finance",
        "automotive",
    ],
    "45-54": ["financial-services", "travel-hospitality", "wellness", "automotive"],
    "55+": [
        "financial-services",
        "travel-hospitality",
        "healthcare-services",
        "real-estate",
    ],
}


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _dominant_age_band(audience_demographics: dict[str, Any]) -> str | None:
    """Return the IAB age band with the highest share."""
    bands = audience_demographics.get("age_bands") or []
    if not isinstance(bands, list):
        return None
    best: tuple[str, float] | None = None
    for entry in bands:
        if not isinstance(entry, dict):
            continue
        band = entry.get("band") or entry.get("age_band") or entry.get("range")
        share = entry.get("share") or entry.get("pct") or entry.get("percent")
        if not isinstance(band, str) or not isinstance(share, int | float):
            continue
        if best is None or share > best[1]:
            best = (band, float(share))
    return best[0] if best else None


def run(
    *,
    audience_demographics: dict[str, Any],
    brand_industry_map: dict[str, Any],
) -> list[CandidateSource]:
    """Surface brands in life-stage industries for the dominant audience age."""
    band = _dominant_age_band(audience_demographics)
    if not band:
        return []
    industries = _LIFE_STAGE_INDUSTRIES.get(band) or []
    if not industries:
        return []

    brands = brand_industry_map.get("brands") or []
    if not isinstance(brands, list):
        return []

    seen: set[str] = set()
    sources: list[CandidateSource] = []
    for entry in brands:
        if not isinstance(entry, dict):
            continue
        industry_id = entry.get("industry_id")
        if not isinstance(industry_id, str) or industry_id not in industries:
            continue
        brand_id = _slugify(entry["name"])
        if brand_id in seen:
            continue
        seen.add(brand_id)
        sources.append(
            CandidateSource(
                brand_id=brand_id,
                brand_name=entry["name"],
                industry_id=industry_id,
                search_tag=_SEARCH_TAG,
                weight=_WEIGHT,
                note=f"Audience life-stage {band} -> industry {industry_id!r}.",
            )
        )
    return sources
