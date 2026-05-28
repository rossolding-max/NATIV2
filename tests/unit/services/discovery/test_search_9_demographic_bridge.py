"""Search 9 (IAB demographic-bridge to industry brands)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.discovery import search_9_demographic_bridge


def _make_taxonomies(affinity_groups: list[dict[str, Any]]) -> MagicMock:
    tax = MagicMock()
    tax.industry_audience_affinity = {"groups": affinity_groups}
    return tax


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def test_unit__no_iab_interests_returns_empty() -> None:
    tax = _make_taxonomies([{"industry_id": "beauty-personal-care", "interest_segments": [677]}])
    bim = _brand_map({"name": "MAC", "industry_id": "beauty-personal-care"})
    sources = search_9_demographic_bridge.run(
        audience_demographics={"interests": []},
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert sources == []


def test_unit__low_overlap_emits_low_weight() -> None:
    tax = _make_taxonomies([{"industry_id": "beauty-personal-care", "interest_segments": [677]}])
    bim = _brand_map({"name": "MAC", "industry_id": "beauty-personal-care"})
    sources = search_9_demographic_bridge.run(
        audience_demographics={"interests": [677]},
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].weight == 0.15
    assert sources[0].search_tag == "demographic_bridge"


def test_unit__high_overlap_emits_high_weight() -> None:
    tax = _make_taxonomies(
        [
            {
                "industry_id": "beauty-personal-care",
                "interest_segments": [1, 2, 3, 4, 5],
            }
        ]
    )
    bim = _brand_map({"name": "MAC", "industry_id": "beauty-personal-care"})
    sources = search_9_demographic_bridge.run(
        audience_demographics={"interests": [1, 2, 3, 4, 5]},
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].weight == 0.25


def test_unit__interests_as_dict_with_iab_segment_id() -> None:
    """Talent profile might store interests as ``{iab_segment_id, label}`` dicts."""
    tax = _make_taxonomies([{"industry_id": "beauty-personal-care", "interest_segments": [677]}])
    bim = _brand_map({"name": "MAC", "industry_id": "beauty-personal-care"})
    sources = search_9_demographic_bridge.run(
        audience_demographics={"interests": [{"iab_segment_id": 677, "label": "Beauty"}]},
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
