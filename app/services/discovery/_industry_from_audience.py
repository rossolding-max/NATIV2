"""M7.7 — Derive industries from audience demographics (formerly S9 logic).

Walks ``industry_audience_affinity.groups`` looking for industries whose
IAB segment tags overlap the talent's audience interests. Returns
IndustryProposals — does NOT surface brands (that's Phase 2's job).
"""

from __future__ import annotations

from typing import Any

from app.services.discovery._models import IndustryProposal
from app.utils.taxonomies import Taxonomies


def _talent_iab_segment_set(audience_demographics: dict[str, Any]) -> set[int]:
    """Extract IAB segment ids the talent's audience overlaps.

    Reads ``audience_demographics.interests[]`` if it carries explicit
    IAB segment ids. The richer derivation (age + country + cohort -> IAB)
    lands later when the talent schema is richer.
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


def derive_industries_from_audience(
    *,
    audience_demographics: dict[str, Any],
    taxonomies: Taxonomies,
) -> list[IndustryProposal]:
    """Return industry proposals for industries with IAB overlap >= 1.

    No-op when the talent has no IAB-tagged interests (common at v0.1
    onboarding — agents don't always fill audience demographics by hand).

    Rationale carries up to 3 example IAB segments to help the operator
    judge whether the proposed industry is genuinely relevant.
    """
    talent_segments = _talent_iab_segment_set(audience_demographics)
    if not talent_segments:
        return []

    affinity_groups = taxonomies.industry_audience_affinity.get("groups") or []
    if not isinstance(affinity_groups, list):
        return []

    out: list[IndustryProposal] = []
    seen: set[str] = set()
    for entry in affinity_groups:
        if not isinstance(entry, dict):
            continue
        industry_id = entry.get("industry_id")
        if not isinstance(industry_id, str) or industry_id in seen:
            continue
        industry_segments = _industry_iab_segment_set(entry)
        overlap = talent_segments & industry_segments
        if not overlap:
            continue
        seen.add(industry_id)
        sample = sorted(overlap)[:3]
        rationale = (
            f"Audience demographic overlap (IAB segments: {sample}, total {len(overlap)} matches)"
        )
        out.append(
            IndustryProposal(
                industry_id=industry_id,
                rationale=rationale,
                source="audience_demographic",
            )
        )
    return out
