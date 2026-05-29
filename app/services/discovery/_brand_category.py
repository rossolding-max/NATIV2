"""M7.7+ — Central source-tag → brand_category mapping.

Every brand in the agency inventory should land with a ``brand_category``
(emerging / growth / established) so the operator can filter, the
prospect lists can segment, and outreach copy can match tone to scale.

Today only the three Phase 2 query families set the category directly.
This module fills the gap for every other source the pipeline uses:

  - Phase 2 (Exa fan-out): explicit category per query family.
  - S1 own past brands / S2 similar-talent: established (they're real
    companies the talent or peers have already partnered with).
  - S3/S4 Exa competitors: established (competing with the past brand
    means commercial scale; we default to established).
  - S15 newly funded / S16 trending / Phase 4 global: emerging
    (recency / fundraise signals are the literal definition).
  - S13 values-aligned / S17 paid social: no inference; values and
    paid-presence are orthogonal to scale.
  - Seed-map walk: inherits from the seed-map entry's stored
    ``brand_category`` if present.

The aggregator walks a candidate's sources in order; the first source
whose tag maps to a category wins. When none do, falls back to the
seed-map entry's stored category. Returns None if neither path yields
a value (rare; only when an unmapped tag stacks on a curated entry
without a stored category).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

BrandCategoryStr = str  # narrowed downstream to Literal["emerging", "growth", "established"]


_VALID_CATEGORIES: frozenset[str] = frozenset({"emerging", "growth", "established"})


CATEGORY_BY_TAG: dict[str, BrandCategoryStr] = {
    # M7.7 Phase 2 query families — authoritative.
    "exa_emerging": "emerging",
    "exa_growth": "growth",
    "exa_established": "established",
    # M7.3-M7.6 legacy Exa tags.
    "recently_funded": "emerging",  # S15 newly funded / Series A-B
    "established_exa_discovery": "established",  # S18 deprecated
    # M7.7 Phase 3 talent-specific.
    "previous_brand_reengage": "established",  # S1 — past partners
    "similar_talent_worked_with": "established",  # S2 — peers' past partners
    "competitor_of_previous": "established",  # S3 — competing past-brand peers
    "competitor_of_similar_talent": "established",  # S4
    # M7.7 Phase 4 signal overlay.
    "global_trending_funded": "emerging",  # Phase 4 S15-residual
    "last30days_trending": "emerging",  # S16 — fresh momentum
    # Tags that don't imply a scale category — leave to entry fallback.
    # "values_aligned_exa": values alignment is orthogonal to scale.
    # "paid_social_*": paid-presence is orthogonal.
    # "seed_map_walk": inherit from the seed-map entry's stored category.
}


def infer_brand_category(
    source_tags: Iterable[str] | list[Any],
    brand_entry: dict[str, Any] | None,
) -> str | None:
    """Best-guess ``brand_category`` for a candidate.

    Priority:
      1. First source whose ``search_tag`` is in ``CATEGORY_BY_TAG``.
      2. The seed-map entry's stored ``brand_category`` (curated or
         discovered file may carry one from a prior run).
      3. None.

    ``source_tags`` may be an iterable of tag strings (use the candidate's
    sources in order — first match wins).
    """
    for tag in source_tags:
        if not isinstance(tag, str):
            continue
        mapped = CATEGORY_BY_TAG.get(tag)
        if mapped:
            return mapped

    if isinstance(brand_entry, dict):
        stored = brand_entry.get("brand_category")
        if isinstance(stored, str) and stored in _VALID_CATEGORIES:
            return stored

    return None
