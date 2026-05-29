"""M7.7+ Phase 2 — Seed-map walk: emit candidates from accumulated inventory.

The merged seed map (``brand_industry_map.json`` curated + auto-grown
``brand_industry_map_discovered.json``) accumulates every brand the
agency has surfaced across all talents over time. Today every Phase 2
Exa fan-out re-pays for brands already known, because the seed map is
only used for canonicalisation — not for emitting candidates.

This module closes that loop. For each approved industry (plus its
sub-industries), walk the merged seed map and emit one
``CandidateSource`` per matching brand. Tag ``seed_map_walk``, weight
0.30 (same as v1's S5 primary affinity walk — these are known brands
explicitly tagged with the industry, so high signal).

Cost-saving shape over time:

  - Run 1 of niche X: Exa surfaces ~1500 brands; seed map grows.
  - Run 2 of niche X (different talent): seed-map walk emits ~1500
    candidates *for free*; Exa fan-out still runs but most hits
    canonicalise to existing entries, so net-new growth tapers.
  - Long-run: the discovered map saturates per industry. Exa keeps
    bringing freshness (new social handles, new launches) but the
    bulk of the candidate set comes from the seed-map walk.

The Exa fan-out is never skipped — it remains the freshness mechanism.
What changes is which leg of Phase 2 carries the volume.
"""

from __future__ import annotations

from typing import Any

from app.services.discovery._models import CandidateSource
from app.utils.logging import get_logger
from app.utils.slugify import slugify_brand_name

log = get_logger(__name__)


SEARCH_TAG: str = "seed_map_walk"
_WEIGHT: float = 0.30


def _expansion_set(approved_industries: list[str], taxonomies: Any) -> set[str]:
    """Expand approved industries to include their sub-industries.

    If the operator approved a top-level sector like ``fashion``, brands
    tagged with child industries (``fashion-streetwear``, ``footwear``,
    etc.) should also surface. If the operator approved a leaf directly,
    children list is empty and only the leaf matches.
    """
    expanded: set[str] = set()
    for iid in approved_industries:
        if not iid:
            continue
        expanded.add(iid)
        try:
            children = taxonomies.get_sub_industries(iid) or []
        except Exception:  # pragma: no cover - defensive
            children = []
        for child in children:
            if isinstance(child, str) and child:
                expanded.add(child)
    return expanded


def run(
    *,
    approved_industries: list[str],
    brand_industry_map: dict[str, Any],
    taxonomies: Any,
) -> list[CandidateSource]:
    """Emit one source per seed-map brand whose industry is approved.

    Matches on the brand's ``industry_id`` first, then ``sub_industry_id``
    (M7.7+ field). De-dupes by ``brand_id`` so a single brand surfaces
    at most once even if it sits under multiple matching tags.
    """
    if not approved_industries:
        return []

    expansion = _expansion_set(approved_industries, taxonomies)
    if not expansion:
        return []

    brands = brand_industry_map.get("brands") or []
    seen: set[str] = set()
    sources: list[CandidateSource] = []
    for entry in brands:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue

        primary = entry.get("industry_id") or ""
        sub = entry.get("sub_industry_id") or ""
        match_iid: str | None = None
        if isinstance(primary, str) and primary in expansion:
            match_iid = primary
        elif isinstance(sub, str) and sub in expansion:
            match_iid = sub
        if match_iid is None:
            continue

        brand_id = entry.get("brand_id")
        if not isinstance(brand_id, str) or not brand_id:
            brand_id = slugify_brand_name(name)
        if not brand_id or brand_id in seen:
            continue
        seen.add(brand_id)

        emit_industry = primary if isinstance(primary, str) and primary else sub
        note = (
            f"Seed-map walk: brand already in agency inventory under "
            f"industry={emit_industry!r}; matched approved industry={match_iid!r}"
        )[:380]

        sources.append(
            CandidateSource(
                brand_id=brand_id,
                brand_name=name,
                industry_id=emit_industry or match_iid,
                search_tag=SEARCH_TAG,
                weight=_WEIGHT,
                note=note,
                brand_domain=entry.get("domain") if isinstance(entry.get("domain"), str) else None,
                brand_social_handles=(
                    entry.get("social_handles")
                    if isinstance(entry.get("social_handles"), dict)
                    else None
                ),
            )
        )

    log.info(
        "phase_2_seed_map_walk_emitted",
        approved=len(approved_industries),
        expansion=len(expansion),
        seed_brands=len(brands),
        emitted=len(sources),
    )
    return sources
