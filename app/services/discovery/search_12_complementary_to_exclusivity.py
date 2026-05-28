"""Search 12 — complementary categories around active exclusivities.

For each active exclusivity in ``talent.brand_preferences.active_exclusivities[]``,
the same INDUSTRY is policy-blocked (handled in ``policy_filter``).
But ADJACENT industries (siblings under the same parent industry, or
the parent itself) are still fair game and often higher-fit because the
audience already responded well to the category.

E.g. talent has an exclusivity with Gymshark (activewear). Search 12
surfaces brands in ``athleisure``, ``sports-nutrition``, ``fitness-tech``
— adjacent categories the audience already buys into.

Low weight (0.05) because the signal is "the audience tolerates THIS
category", not a direct fit.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any

from app.services.discovery._models import CandidateSource
from app.utils.taxonomies import Taxonomies

_SEARCH_TAG: str = "complementary_to_exclusivity"
_WEIGHT: float = 0.05


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _is_active(exclusivity: dict[str, Any], today: date) -> bool:
    ends = exclusivity.get("ends_on")
    if not ends:
        return True
    if isinstance(ends, date):
        return ends >= today
    if isinstance(ends, str):
        try:
            return date.fromisoformat(ends[:10]) >= today
        except ValueError:
            return False
    return False


def _adjacent_industries(*, industry_id: str, taxonomies: Taxonomies) -> set[str]:
    """Return the industry's parent + sibling industries (NOT the industry itself)."""
    own = taxonomies.get_industry(industry_id)
    if not own:
        return set()
    parent_id = own.get("parent")
    adjacent: set[str] = set()
    if parent_id:
        adjacent.add(parent_id)
        # All children of the same parent (siblings).
        for iid, node in taxonomies.industries.items():
            if node.get("parent") == parent_id and iid != industry_id:
                adjacent.add(iid)
    return adjacent


def run(
    *,
    brand_preferences: dict[str, Any],
    taxonomies: Taxonomies,
    brand_industry_map: dict[str, Any],
    today: date | None = None,
) -> list[CandidateSource]:
    """Surface brands in industries adjacent to the talent's active exclusivities."""
    today_dt = today or datetime.now(UTC).date()
    active_exclusivities = brand_preferences.get("active_exclusivities") or []
    if not isinstance(active_exclusivities, list):
        return []

    exclusive_industry_ids: set[str] = set()
    adjacent_ids: set[str] = set()
    for entry in active_exclusivities:
        if not isinstance(entry, dict) or not _is_active(entry, today_dt):
            continue
        industry_id = entry.get("industry_id")
        if isinstance(industry_id, str):
            exclusive_industry_ids.add(industry_id)
            adjacent_ids.update(
                _adjacent_industries(industry_id=industry_id, taxonomies=taxonomies)
            )
    # Strip the exclusivity industries themselves (those are policy-blocked).
    adjacent_ids -= exclusive_industry_ids
    if not adjacent_ids:
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
        if not isinstance(industry_id, str) or industry_id not in adjacent_ids:
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
                note=f"Adjacent to exclusivity industries: {sorted(exclusive_industry_ids)}.",
            )
        )
    return sources
