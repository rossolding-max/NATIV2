"""Search 2 — brands similar talents have worked with.

Walks ``talent.data.similar_talent[]`` (manual seeds + LLM suggestions
from M5 Step 7) and surfaces each entry's ``previous_brands[]`` as
candidates. Weight scales with the count of similar-talents that share
the brand — if 3 of your comparable creators all worked with a brand,
that's a stronger signal than a one-off mention.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.discovery._models import CandidateSource

_BASE_WEIGHT: float = 0.10
_MAX_WEIGHT: float = 0.20
_SEARCH_TAG: str = "similar_talent_worked_with"


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _build_brand_index(brand_industry_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index ``brand_industry_map.brands[]`` by lowercase name + aliases."""
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
    brand_industry_map: dict[str, Any],
) -> list[CandidateSource]:
    """Surface brands that the talent's similar-talent seeds have worked with."""
    brand_index = _build_brand_index(brand_industry_map)
    # Count mentions per brand across all similar talents.
    mentions: dict[str, int] = {}
    brand_meta: dict[str, dict[str, Any]] = {}
    for sim in similar_talent:
        if not isinstance(sim, dict):
            continue
        previous = sim.get("previous_brands") or []
        if not isinstance(previous, list):
            continue
        seen_in_this_talent: set[str] = set()
        for pb in previous:
            if not isinstance(pb, dict):
                continue
            brand_name = pb.get("brand") or pb.get("name")
            if not isinstance(brand_name, str):
                continue
            entry = brand_index.get(brand_name.strip().lower())
            if entry is None or not entry.get("industry_id"):
                continue
            brand_id = _slugify(entry["name"])
            if brand_id in seen_in_this_talent:
                continue
            seen_in_this_talent.add(brand_id)
            mentions[brand_id] = mentions.get(brand_id, 0) + 1
            brand_meta[brand_id] = entry

    sources: list[CandidateSource] = []
    for brand_id, count in mentions.items():
        entry = brand_meta[brand_id]
        # Scale weight: 1 mention → 0.10, 3+ mentions → 0.20.
        weight = _BASE_WEIGHT + (_MAX_WEIGHT - _BASE_WEIGHT) * min(1.0, (count - 1) / 2.0)
        sources.append(
            CandidateSource(
                brand_id=brand_id,
                brand_name=entry["name"],
                industry_id=entry["industry_id"],
                search_tag=_SEARCH_TAG,
                weight=weight,
                note=f"{count} similar-talent(s) worked with this brand.",
            )
        )
    return sources
