"""Search 14 — 2nd-degree competitor graph expansion.

For each direct competitor surfaced by Search 3 (competitors of the
talent's previous brands), walk the competitor graph ONE more hop —
the competitor's competitors. These are 2 graph hops from the talent's
own deals.

Low weight (0.03) because each extra hop dilutes the signal. Useful as
a long-tail expander when Searches 3 + 4 don't produce enough volume.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.discovery._models import CandidateSource
from app.utils.taxonomies import Taxonomies

_SEARCH_TAG: str = "graph_expansion_2nd_degree"
_WEIGHT: float = 0.03


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
    previous_brands: list[Any],
    taxonomies: Taxonomies,
    brand_industry_map: dict[str, Any],
) -> list[CandidateSource]:
    """Walk talent's brands -> competitors -> competitors-of-competitors -> sources."""
    brand_index = _build_brand_index(brand_industry_map)

    # First hop: direct competitors of the talent's previous brands.
    first_hop_names: set[str] = set()
    direct_excludes: set[str] = {
        str(pb.get("brand") or pb.get("name") or "").strip().lower()
        for pb in previous_brands
        if isinstance(pb, dict)
    } - {""}
    for past in previous_brands:
        if not isinstance(past, dict):
            continue
        past_name = past.get("brand") or past.get("name")
        if not isinstance(past_name, str):
            continue
        for competitor_name in taxonomies.get_competitors(past_name):
            first_hop_names.add(competitor_name.strip())

    # Second hop: competitors of those competitors.
    seen: set[str] = set()
    sources: list[CandidateSource] = []
    for first_hop_name in first_hop_names:
        for second_hop_name in taxonomies.get_competitors(first_hop_name):
            key = second_hop_name.strip().lower()
            if not key or key in seen or key in direct_excludes:
                continue
            # Also exclude the first-hop set so Search 3 / 4 isn't double-counted.
            if any(key == f.strip().lower() for f in first_hop_names):
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
                    note=f"2nd-degree competitor (via {first_hop_name}).",
                )
            )
    return sources
