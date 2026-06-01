"""Search 8 — brands in parent + sibling niches' industries.

Extends Searches 5/6/7 by walking the niche taxonomy: for each of the
talent's content niches, climb to the ``parent`` niche (per
``data/niches.json``) and then enumerate its other children (siblings)
plus the parent itself. For each surfaced niche, pull the PRIMARY tier
industries from ``niche_industry_affinity.json`` and surface brands in
them.

Lower weight (0.08) than direct niche searches — siblings are
adjacent, not direct. Dedupes against the original content_niches so
Search 5/6/7's signal isn't double-counted.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.discovery._models import CandidateSource
from app.utils.taxonomies import Taxonomies

_SEARCH_TAG: str = "parent_sibling_niche"
_WEIGHT: float = 0.08
# M7.3 — same sub-industry decay rule as Search 5/6/7.
_SUB_INDUSTRY_WEIGHT_DECAY: float = 0.8


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _siblings(*, niche_id: str, taxonomies: Taxonomies) -> set[str]:
    """All other niches sharing the same parent (excluding the niche itself)."""
    own = taxonomies.get_niche(niche_id)
    if not own:
        return set()
    parent_id = own.get("parent")
    if not parent_id:
        return set()
    siblings: set[str] = set()
    for nid, node in taxonomies.niches.items():
        if node.get("parent") == parent_id and nid != niche_id:
            siblings.add(nid)
    return siblings


def _primary_industries_for_niche(
    *, niche_id: str, niche_industry_affinity: dict[str, Any]
) -> list[str]:
    groups = niche_industry_affinity.get("groups") or []
    if not isinstance(groups, list):
        return []
    for group in groups:
        if isinstance(group, dict) and group.get("niche_id") == niche_id:
            return [i for i in (group.get("primary") or []) if isinstance(i, str)]
    return []


def run(
    *,
    content_niches: list[Any],
    taxonomies: Taxonomies,
    brand_industry_map: dict[str, Any],
) -> list[CandidateSource]:
    """Walk parent + sibling niches; surface brands in their primary industries."""
    own_niches: set[str] = {n for n in content_niches if isinstance(n, str)}
    expansion: set[str] = set()
    for niche_id in own_niches:
        own = taxonomies.get_niche(niche_id)
        if own and own.get("parent"):
            expansion.add(own["parent"])  # parent niche itself
        expansion.update(_siblings(niche_id=niche_id, taxonomies=taxonomies))
    # Exclude any niches already in talent.content_niches (Search 5/6/7
    # already surfaced these).
    expansion -= own_niches

    if not expansion:
        return []

    brands = brand_industry_map.get("brands") or []
    if not isinstance(brands, list):
        return []

    seen: set[str] = set()
    sources: list[CandidateSource] = []
    for niche_id in expansion:
        for target_industry_id in _primary_industries_for_niche(
            niche_id=niche_id, niche_industry_affinity=taxonomies.niche_industry_affinity
        ):
            # M7.3 — expand the target industry into itself + its
            # sub-industries. Parent hit gets full weight; sub gets decayed.
            expansions: list[tuple[str, bool]] = [(target_industry_id, False)]
            for child_id in taxonomies.get_sub_industries(target_industry_id):
                expansions.append((child_id, True))

            for expanded_id, is_sub in expansions:
                weight = _WEIGHT * _SUB_INDUSTRY_WEIGHT_DECAY if is_sub else _WEIGHT
                note_suffix = (
                    f" via sub-industry {expanded_id!r} of {target_industry_id!r}" if is_sub else ""
                )
                for entry in brands:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("industry_id") != expanded_id:
                        continue
                    brand_id = _slugify(entry["name"])
                    if brand_id in seen:
                        continue
                    seen.add(brand_id)
                    sources.append(
                        CandidateSource(
                            brand_id=brand_id,
                            brand_name=entry["name"],
                            industry_id=expanded_id,
                            search_tag=_SEARCH_TAG,
                            weight=weight,
                            note=(
                                f"Adjacent niche {niche_id!r} -> primary industry "
                                f"{target_industry_id!r}{note_suffix}."
                            ),
                        )
                    )
    return sources
