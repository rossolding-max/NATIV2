"""Searches 5/6/7 — brands in primary / secondary / tertiary industries.

For every niche in ``talent.data.content_niches[]``, walk
``data/niche_industry_affinity.json`` for the niche's ``primary[]``,
``secondary[]``, ``tertiary[]`` industry lists. For each industry,
enumerate brands from ``brand_industry_map.json`` and surface them as
candidate sources with the tier-specific weight.

The three "logical searches" 5, 6, 7 share one module because the only
difference is which tier of the affinity graph we walk + the weight we
assign.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from app.services.discovery._models import CandidateSource
from app.utils.taxonomies import Taxonomies

_TIER_WEIGHTS: dict[str, float] = {
    "primary": 0.30,
    "secondary": 0.20,
    "tertiary": 0.06,
}

_TIER_TAGS: dict[str, str] = {
    "primary": "primary_industry",
    "secondary": "secondary_industry",
    "tertiary": "tertiary_industry",
}

# M7.3 — sub-industry decay. A brand that's matched via the PARENT
# industry the talent's niche affinity pointed at keeps the full tier
# weight; a brand matched via a SUB-INDUSTRY of that parent gets the
# decayed weight (slightly less direct signal). The "via" provenance
# is recorded in the CandidateSource note for audit.
_SUB_INDUSTRY_WEIGHT_DECAY: float = 0.8

Tier = Literal["primary", "secondary", "tertiary"]


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _industries_for_niche(
    *, niche_id: str, tier: Tier, niche_industry_affinity: dict[str, Any]
) -> list[str]:
    """Read the niche_industry_affinity groups[] and pull the tier list."""
    groups = niche_industry_affinity.get("groups") or []
    if not isinstance(groups, list):
        return []
    for group in groups:
        if not isinstance(group, dict):
            continue
        if group.get("niche_id") == niche_id:
            tier_list = group.get(tier) or []
            return [i for i in tier_list if isinstance(i, str)]
    return []


def _brands_in_industry(
    *, industry_id: str, brand_industry_map: dict[str, Any]
) -> list[dict[str, Any]]:
    brands = brand_industry_map.get("brands") or []
    if not isinstance(brands, list):
        return []
    return [b for b in brands if isinstance(b, dict) and b.get("industry_id") == industry_id]


def _expand_industry_with_sub_industries(
    industry_id: str, taxonomies: Taxonomies
) -> list[tuple[str, bool]]:
    """Return [(industry_id, is_sub_industry), ...] for one target industry.

    The first entry is the target itself (is_sub_industry=False). When the
    target is a parent sector, each direct child is appended with
    is_sub_industry=True so the search emits hits at decayed weight.
    """
    out: list[tuple[str, bool]] = [(industry_id, False)]
    for child_id in taxonomies.get_sub_industries(industry_id):
        out.append((child_id, True))
    return out


def run(
    *,
    content_niches: list[Any],
    tier: Tier,
    taxonomies: Taxonomies,
    brand_industry_map: dict[str, Any],
) -> list[CandidateSource]:
    """Enumerate brands in the tier-N industries for the talent's niches.

    Dedupes across niches so a brand sitting in two niches' primary tier
    only emits one source for this tier. M7.3 — each affinity-target
    industry is expanded into its sub-industries via
    ``taxonomies.get_sub_industries``; brands matched through the sub
    get the tier weight multiplied by ``_SUB_INDUSTRY_WEIGHT_DECAY``.
    When the same brand is reachable via parent AND child, the parent
    hit wins (it emits first, deduper drops the child).
    """
    if tier not in _TIER_WEIGHTS:
        return []
    base_weight = _TIER_WEIGHTS[tier]
    decayed_weight = base_weight * _SUB_INDUSTRY_WEIGHT_DECAY
    tag = _TIER_TAGS[tier]
    seen_brand_ids: set[str] = set()
    sources: list[CandidateSource] = []
    for niche_id in content_niches:
        if not isinstance(niche_id, str):
            continue
        for target_industry_id in _industries_for_niche(
            niche_id=niche_id,
            tier=tier,
            niche_industry_affinity=taxonomies.niche_industry_affinity,
        ):
            for expanded_id, is_sub in _expand_industry_with_sub_industries(
                target_industry_id, taxonomies
            ):
                weight = decayed_weight if is_sub else base_weight
                note_suffix = (
                    f" via sub-industry {expanded_id!r} of {target_industry_id!r}" if is_sub else ""
                )
                for brand_entry in _brands_in_industry(
                    industry_id=expanded_id, brand_industry_map=brand_industry_map
                ):
                    brand_id = _slugify(brand_entry["name"])
                    if brand_id in seen_brand_ids:
                        continue
                    seen_brand_ids.add(brand_id)
                    sources.append(
                        CandidateSource(
                            brand_id=brand_id,
                            brand_name=brand_entry["name"],
                            industry_id=expanded_id,
                            search_tag=tag,
                            weight=weight,
                            note=(
                                f"Niche {niche_id!r} -> {tier} industry "
                                f"{target_industry_id!r}{note_suffix}."
                            ),
                        )
                    )
    return sources
