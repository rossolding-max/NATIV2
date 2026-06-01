"""M7.7 — Derive industries adjacent to active exclusivities (formerly S12 logic).

For each active brand exclusivity the talent has, surface the parent +
sibling industries as candidates. The exclusivity industry itself is
policy-blocked (handled by ``policy_filter``); adjacent categories are
fair game and often higher-fit because the audience already responds to
the broader category.

Returns IndustryProposals — does NOT surface brands.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from app.services.discovery._models import IndustryProposal
from app.utils.taxonomies import Taxonomies


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
    """Return parent + sibling industries of ``industry_id``."""
    own = taxonomies.get_industry(industry_id)
    if not own:
        return set()
    parent_id = own.get("parent")
    adjacent: set[str] = set()
    if parent_id:
        adjacent.add(parent_id)
        for iid, node in taxonomies.industries.items():
            if node.get("parent") == parent_id and iid != industry_id:
                adjacent.add(iid)
    return adjacent


def derive_industries_from_exclusivities(
    *,
    brand_preferences: dict[str, Any],
    taxonomies: Taxonomies,
    today: date | None = None,
) -> list[IndustryProposal]:
    """Return industry proposals for industries adjacent to active exclusivities.

    No-op when the talent has no active exclusivities. Each proposal's
    rationale names the exclusivity-holding brand so the operator knows
    why this industry is in scope.
    """
    today_dt = today or datetime.now(UTC).date()
    active_exclusivities = brand_preferences.get("active_exclusivities") or []
    if not isinstance(active_exclusivities, list):
        return []

    # Index: adjacent industry_id -> list of (exclusive_brand_name, exclusive_industry_id)
    adjacent_by_industry: dict[str, list[tuple[str, str]]] = {}
    exclusive_industry_ids: set[str] = set()
    for entry in active_exclusivities:
        if not isinstance(entry, dict) or not _is_active(entry, today_dt):
            continue
        industry_id = entry.get("industry_id")
        brand_name = entry.get("brand") or entry.get("brand_name") or "unknown brand"
        if not isinstance(industry_id, str):
            continue
        exclusive_industry_ids.add(industry_id)
        for adj in _adjacent_industries(industry_id=industry_id, taxonomies=taxonomies):
            adjacent_by_industry.setdefault(adj, []).append((str(brand_name), industry_id))

    # Drop exclusivity industries themselves (policy-blocked).
    for excl in exclusive_industry_ids:
        adjacent_by_industry.pop(excl, None)

    out: list[IndustryProposal] = []
    for adj_industry_id, reasons in adjacent_by_industry.items():
        # Use the first exclusivity that surfaced this adjacency.
        brand_name, source_industry = reasons[0]
        rationale = (
            f"Exclusivity adjacency: complementary to active exclusive with "
            f"{brand_name!r} (industry {source_industry!r})"
        )
        out.append(
            IndustryProposal(
                industry_id=adj_industry_id,
                rationale=rationale,
                source="exclusivity_adjacent",
            )
        )
    return out
