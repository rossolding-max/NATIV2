"""Search 9 — demographic bridge from audience to industries.

The talent's audience demographics (age bands, top countries, interests)
map to IAB Audience Taxonomy segments. ``industry_audience_affinity``
maps industries to the same IAB segments. Industries that share a high
number of IAB segments with the talent's audience are "demographically
bridged" — surface brands in those industries as candidates.

v0.1 implementation: lightweight overlap count, not a sophisticated
similarity score. The full IAB scoring lands in M7.1 when the talent
audience-demographics shape is richer.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.discovery._models import CandidateSource
from app.utils.taxonomies import Taxonomies

# Weight scales with overlap strength: 0.15 (1-2 IAB matches), 0.20
# (3-4 matches), 0.25 (5+).
_WEIGHT_BY_OVERLAP_BUCKET: dict[str, float] = {
    "low": 0.15,
    "medium": 0.20,
    "high": 0.25,
}


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _talent_iab_segment_set(audience_demographics: dict[str, Any]) -> set[int]:
    """Extract IAB segment ids the talent's audience overlaps.

    v0.1 reads ``audience_demographics.interests[]`` if it carries
    explicit IAB segment ids. The richer derivation (age + country +
    cohort -> IAB) lands when the talent schema fills out — for now we
    only pull explicit interest ids.
    """
    segments: set[int] = set()
    interests = audience_demographics.get("interests") or []
    if isinstance(interests, list):
        for item in interests:
            if isinstance(item, dict):
                seg = item.get("iab_segment_id") or item.get("id")
                if isinstance(seg, int):
                    segments.add(seg)
            elif isinstance(item, int):
                segments.add(item)
    return segments


def _industry_iab_segment_set(industry_entry: dict[str, Any]) -> set[int]:
    """Collect IAB segments tagged on an industry-audience-affinity entry."""
    segments: set[int] = set()
    for key in ("interest_segments", "purchase_intent_segments", "demographic_segments"):
        for seg in industry_entry.get(key) or []:
            if isinstance(seg, int):
                segments.add(seg)
    return segments


def _bucket_for_overlap(count: int) -> str | None:
    if count >= 5:
        return "high"
    if count >= 3:
        return "medium"
    if count >= 1:
        return "low"
    return None


def run(
    *,
    audience_demographics: dict[str, Any],
    taxonomies: Taxonomies,
    brand_industry_map: dict[str, Any],
) -> list[CandidateSource]:
    """Find industries with high IAB overlap; surface brands inside them.

    No-op when the talent has no IAB-tagged interests (common at v0.1
    onboarding — agents don't fill audience demographics by hand).
    """
    talent_segments = _talent_iab_segment_set(audience_demographics)
    if not talent_segments:
        return []

    affinity_groups = taxonomies.industry_audience_affinity.get("groups") or []
    if not isinstance(affinity_groups, list):
        return []

    industry_weights: dict[str, float] = {}
    for entry in affinity_groups:
        if not isinstance(entry, dict):
            continue
        industry_id = entry.get("industry_id")
        if not industry_id:
            continue
        industry_segments = _industry_iab_segment_set(entry)
        overlap = len(talent_segments & industry_segments)
        bucket = _bucket_for_overlap(overlap)
        if bucket is None:
            continue
        industry_weights[industry_id] = _WEIGHT_BY_OVERLAP_BUCKET[bucket]

    seen: set[str] = set()
    sources: list[CandidateSource] = []
    brands = brand_industry_map.get("brands") or []
    if not isinstance(brands, list):
        return sources
    for brand_entry in brands:
        if not isinstance(brand_entry, dict):
            continue
        industry_id = brand_entry.get("industry_id")
        if not isinstance(industry_id, str):
            continue
        weight = industry_weights.get(industry_id)
        if weight is None:
            continue
        brand_id = _slugify(brand_entry["name"])
        if brand_id in seen:
            continue
        seen.add(brand_id)
        sources.append(
            CandidateSource(
                brand_id=brand_id,
                brand_name=brand_entry["name"],
                industry_id=industry_id,
                search_tag="demographic_bridge",
                weight=weight,
                note=f"IAB segment overlap with industry {industry_id!r}.",
            )
        )
    return sources
