"""Search 3 — direct competitors of the talent's previous brands.

For every entry in ``talent.data.previous_brands[]``, look up the
``data/brand_competitors.json`` graph (loaded via ``Taxonomies``) and
surface each competitor as a candidate. The competitor needs to be
resolvable to a ``brand_id`` slug + ``industry_id`` via the seed
``brand_industry_map.json`` — anything not in the seed map is dropped
(M9 surfaces a "follow-up: enrich this brand" task).
"""

from __future__ import annotations

import re
from typing import Any

from app.services.discovery._models import CandidateSource
from app.utils.taxonomies import Taxonomies

_SEARCH_WEIGHT: float = 0.25


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _build_brand_index(brand_industry_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index ``data/brand_industry_map.json`` entries by lowercase name + aliases."""
    index: dict[str, dict[str, Any]] = {}
    brands = brand_industry_map.get("brands") or []
    if not isinstance(brands, list):
        return index
    for entry in brands:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        if not name:
            continue
        index[name.lower()] = entry
        for alias in entry.get("aliases") or []:
            if isinstance(alias, str) and alias.strip():
                index[alias.strip().lower()] = entry
    return index


def run(
    *,
    previous_brands: list[Any],
    taxonomies: Taxonomies,
    brand_industry_map: dict[str, Any],
) -> list[CandidateSource]:
    """Walk talent.previous_brands -> competitors -> CandidateSources.

    Dedupes across past brands so the same competitor doesn't double-count
    (e.g. talent worked with both Gymshark and Nike; Adidas only emits
    one source even if it competes with both).
    """
    brand_index = _build_brand_index(brand_industry_map)
    seen: set[str] = set()
    sources: list[CandidateSource] = []

    for past in previous_brands:
        if not isinstance(past, dict):
            continue
        past_name = str(past.get("brand") or past.get("name") or "").strip()
        if not past_name:
            continue
        # Taxonomies' brand_competitors graph is keyed by display name.
        for competitor_name in taxonomies.get_competitors(past_name):
            key = competitor_name.strip().lower()
            if not key or key in seen:
                continue
            brand_entry = brand_index.get(key)
            if brand_entry is None:
                # Competitor not in seed map — skip; downstream enrichment
                # will pull it in later when M7.1 / M9 hits unknown brands.
                continue
            industry_id = brand_entry.get("industry_id")
            if not industry_id:
                continue
            seen.add(key)
            sources.append(
                CandidateSource(
                    brand_id=_slugify(brand_entry["name"]),
                    brand_name=brand_entry["name"],
                    industry_id=industry_id,
                    search_tag="competitor_of_previous",
                    weight=_SEARCH_WEIGHT,
                    note=f"Direct competitor of {past_name}.",
                )
            )
    return sources
