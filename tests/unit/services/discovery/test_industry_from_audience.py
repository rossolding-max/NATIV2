"""M7.7 — Audience-demographic → industry derivation tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.discovery._industry_from_audience import (
    derive_industries_from_audience,
)


def _mock_tax(affinity_groups: list[dict[str, Any]]) -> MagicMock:
    tax = MagicMock()
    tax.industry_audience_affinity = {"groups": affinity_groups}
    return tax


def test_unit__audience__empty_when_no_interests() -> None:
    tax = _mock_tax([])
    out = derive_industries_from_audience(audience_demographics={}, taxonomies=tax)
    assert out == []


def test_unit__audience__matches_industry_via_iab_segment_overlap() -> None:
    """A talent with IAB segment 200 surfaces industries that tag segment 200."""
    audience = {"interests": [{"iab_segment_id": 200}, {"iab_segment_id": 300}]}
    tax = _mock_tax(
        [
            {"industry_id": "femtech", "interest_segments": [200]},
            {"industry_id": "telehealth", "interest_segments": [400]},  # no overlap
            {"industry_id": "wellness", "purchase_intent_segments": [200, 300]},
        ]
    )
    out = derive_industries_from_audience(audience_demographics=audience, taxonomies=tax)
    ids = {p.industry_id for p in out}
    assert ids == {"femtech", "wellness"}
    # Rationale carries the matched segments.
    femtech = next(p for p in out if p.industry_id == "femtech")
    assert "200" in femtech.rationale
    assert femtech.source == "audience_demographic"


def test_unit__audience__sorted_iab_sample_capped_at_3_in_rationale() -> None:
    audience = {"interests": [{"iab_segment_id": i} for i in (10, 20, 30, 40, 50)]}
    tax = _mock_tax(
        [
            {
                "industry_id": "broad-overlap",
                "interest_segments": [10, 20, 30, 40, 50],
            }
        ]
    )
    out = derive_industries_from_audience(audience_demographics=audience, taxonomies=tax)
    assert len(out) == 1
    # rationale shows first 3 segments
    assert "[10, 20, 30]" in out[0].rationale
    assert "total 5 matches" in out[0].rationale


def test_unit__audience__bare_int_interests_supported() -> None:
    """Talent interests can be bare ints or dict {iab_segment_id: int}."""
    audience = {"interests": [200, 300]}
    tax = _mock_tax([{"industry_id": "wellness", "interest_segments": [200]}])
    out = derive_industries_from_audience(audience_demographics=audience, taxonomies=tax)
    assert {p.industry_id for p in out} == {"wellness"}


def test_unit__audience__skips_non_dict_affinity_entries() -> None:
    audience = {"interests": [200]}
    tax = _mock_tax([{"industry_id": "wellness", "interest_segments": [200]}, "not a dict"])  # type: ignore[list-item]
    out = derive_industries_from_audience(audience_demographics=audience, taxonomies=tax)
    assert len(out) == 1
