"""Search 4 — competitors of brands that similar talents have worked with.

Composition of Search 2 + Search 3: for each brand surfaced by Search 2,
walk the ``data/brand_competitors.json`` graph and surface each
competitor as a CandidateSource. The signal is weaker than direct
competitors of the talent's OWN previous brands (Search 3, weight 0.25)
because we're now 2 graph hops from the talent.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.discovery._models import CandidateSource
from app.utils.taxonomies import Taxonomies

_SEARCH_TAG: str = "competitor_of_similar_talent"
_WEIGHT: float = 0.10


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _build_brand_index(brand_industry_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for entry in brand_industry_map.get("brands") or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if isinstance(name, str):
            index[name.strip().lower()] = entry
        for alias in entry.get("aliases") or []:
            if isinstance(alias, str):
                index[alias.strip().lower()] = entry
    return index


def run(
    *,
    similar_talent: list[Any],
    taxonomies: Taxonomies,
    brand_industry_map: dict[str, Any],
) -> list[CandidateSource]:
    """Walk similar-talent brands -> competitor graph -> CandidateSources."""
    brand_index = _build_brand_index(brand_industry_map)
    seen: set[str] = set()
    sources: list[CandidateSource] = []

    for sim in similar_talent:
        if not isinstance(sim, dict):
            continue
        previous = sim.get("previous_brands") or []
        if not isinstance(previous, list):
            continue
        for pb in previous:
            if not isinstance(pb, dict):
                continue
            past_name = pb.get("brand") or pb.get("name")
            if not isinstance(past_name, str):
                continue
            for competitor_name in taxonomies.get_competitors(past_name):
                key = competitor_name.strip().lower()
                if not key or key in seen:
                    continue
                entry = brand_index.get(key)
                if entry is None or not entry.get("industry_id"):
                    continue
                seen.add(key)
                sources.append(
                    CandidateSource(
                        brand_id=_slugify(entry["name"]),
                        brand_name=entry["name"],
                        industry_id=entry["industry_id"],
                        search_tag=_SEARCH_TAG,
                        weight=_WEIGHT,
                        note=f"Competitor of {past_name!r} (worked with similar talent).",
                    )
                )
    return sources
