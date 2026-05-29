"""M7.7 — Derive industries from audience life-stage (formerly S11 logic).

Returns IndustryProposals based on the dominant age band of the talent's
audience. Does NOT surface brands.
"""

from __future__ import annotations

from typing import Any

from app.services.discovery._models import IndustryProposal

# Inline life-stage -> industry map. Derived from IAB Purchase Intent
# segments per age cohort.
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


def _dominant_age_band(audience_demographics: dict[str, Any]) -> str | None:
    """Return the age band with the highest share among the audience."""
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


def derive_industries_from_life_stage(
    *,
    audience_demographics: dict[str, Any],
) -> list[IndustryProposal]:
    """Return industry proposals for the dominant audience life-stage.

    No-op when the talent's audience demographics don't include an
    ``age_bands[]`` shape.
    """
    band = _dominant_age_band(audience_demographics)
    if not band:
        return []
    industries = _LIFE_STAGE_INDUSTRIES.get(band) or []
    if not industries:
        return []
    return [
        IndustryProposal(
            industry_id=industry_id,
            rationale=f"Life stage: dominant audience age band {band!r}",
            source="life_stage",
        )
        for industry_id in industries
    ]
