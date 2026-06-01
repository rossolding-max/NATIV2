"""Shared geographic-match utilities (M7.3).

Single source of truth for "does this brand operate where the talent's
audience is?". Used as:

- A POST-merge filter in the orchestrator — drops brands whose
  ``sells_in_countries`` is an explicit list NOT including the talent's
  countries (so UK-only retailers don't surface for US creators).
- A reusable helper inside Search 10 (geographic alignment) which uses
  the same talent-country extraction logic.

**Policy decision (locked in M7.3):** soft floor. A brand passes geo when
ANY of the following is true:
- ``sells_in_countries == "global"`` (or a list containing "GLOBAL").
- ``sells_in_countries`` field is absent / empty (assume global until
  proven otherwise — avoids dropping ~half the seed map where geo isn't
  populated).
- ``sells_in_countries`` is a list intersecting the talent's countries.

A brand FAILS geo only when ``sells_in_countries`` is an explicit list
AND none of its values match the talent's countries. This is the case
that catches Tesco (sells_in=['GB','IE']) for a US-based talent.

**Talent geography resolution chain:**
1. ``talent_data.audience_demographics.top_countries[]`` — production
   state, post-OAuth. Top 3 by share, normalised to ISO-3166 alpha-2.
2. ``talent_data.location.country`` — fallback when OAuth was skipped
   (single country, where the talent themselves is based).
3. Empty list — when both are missing. The orchestrator BYPASSES the geo
   filter in that case (no filter applied, all brands surface).
"""

from __future__ import annotations

from typing import Any

from app.services.discovery._models import CandidateSource


def extract_talent_countries(talent_data: dict[str, Any]) -> list[str]:
    """Pull the talent's geographic anchors (ISO-3166 alpha-2 codes).

    Tries audience demographics first (post-OAuth state with real
    audience signal), then falls back to the talent's home country.
    Returns an empty list when both are absent — the caller treats that
    as "no geo filter to apply".
    """
    countries: list[str] = []
    seen: set[str] = set()

    audience = talent_data.get("audience_demographics") or {}
    raw = audience.get("top_countries") if isinstance(audience, dict) else None
    if isinstance(raw, list):
        for item in raw:
            code: str | None = None
            if isinstance(item, str):
                code = item
            elif isinstance(item, dict):
                code = item.get("country") or item.get("code") or item.get("iso2")
            if isinstance(code, str):
                norm = code.strip().upper()
                if norm and norm not in seen:
                    seen.add(norm)
                    countries.append(norm)

    if not countries:
        location = talent_data.get("location") or {}
        if isinstance(location, dict):
            home = location.get("country")
            if isinstance(home, str):
                norm = home.strip().upper()
                if norm:
                    countries.append(norm)

    return countries


def brand_passes_geo(brand_entry: dict[str, Any], talent_countries: list[str]) -> bool:
    """True when the brand should be retained under the geo filter.

    Soft floor: missing geo data on the brand is a pass (assume global).
    Only an EXPLICIT non-matching list drops the brand.
    """
    if not talent_countries:
        # No geo signal for the talent -> filter is bypassed.
        return True

    sells_in = brand_entry.get("sells_in_countries")
    if sells_in is None or sells_in == "":
        # Field absent or blank -> assume global.
        return True

    talent_set = {c.upper() for c in talent_countries}

    if isinstance(sells_in, str):
        # "global" or single-country string.
        return sells_in.strip().upper() in {"GLOBAL", *talent_set}

    if isinstance(sells_in, list):
        if not sells_in:
            # Empty list -> assume global (data tag is present but unfilled).
            return True
        normalized = {(c.strip().upper() if isinstance(c, str) else "") for c in sells_in}
        if "GLOBAL" in normalized:
            return True
        return bool(normalized & talent_set)

    # Unknown shape -> assume global rather than drop.
    return True


def filter_sources_by_geo(
    sources: list[CandidateSource],
    brand_index: dict[str, dict[str, Any]],
    talent_countries: list[str],
) -> list[CandidateSource]:
    """Drop sources whose brand fails geo per the soft-floor rules.

    ``brand_index`` maps lowercased brand name -> brand entry (the same
    index the orchestrator already builds for qualification lookups).
    Sources for brands NOT in the index (Exa-discovered net-new) always
    pass — we can't apply geo without data, but they're tagged
    ``tier="emerging"`` so the agent knows they're lower-trust anyway.

    No-op when ``talent_countries`` is empty (the bypass case).
    """
    if not talent_countries:
        return list(sources)

    kept: list[CandidateSource] = []
    for source in sources:
        brand_entry = brand_index.get(source.brand_name.strip().lower())
        if brand_entry is None:
            kept.append(source)
            continue
        if brand_passes_geo(brand_entry, talent_countries):
            kept.append(source)
    return kept


__all__ = (
    "brand_passes_geo",
    "extract_talent_countries",
    "filter_sources_by_geo",
)
