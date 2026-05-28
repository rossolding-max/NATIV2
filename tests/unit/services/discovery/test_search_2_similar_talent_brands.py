"""Search 2 (brands similar talents have worked with)."""

from __future__ import annotations

from typing import Any

from app.services.discovery import search_2_similar_talent_brands


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def test_unit__search_2__single_similar_talent_brand_emits_base_weight() -> None:
    bim = _brand_map({"name": "Gymshark", "industry_id": "activewear"})
    sources = search_2_similar_talent_brands.run(
        similar_talent=[{"name": "Tammy", "previous_brands": [{"brand": "Gymshark"}]}],
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "gymshark"
    assert sources[0].search_tag == "similar_talent_worked_with"
    assert sources[0].weight == 0.10


def test_unit__search_2__weight_scales_with_mention_count() -> None:
    """Three similar talents working with same brand -> max weight 0.20."""
    bim = _brand_map({"name": "Gymshark", "industry_id": "activewear"})
    sources = search_2_similar_talent_brands.run(
        similar_talent=[
            {"name": "A", "previous_brands": [{"brand": "Gymshark"}]},
            {"name": "B", "previous_brands": [{"brand": "Gymshark"}]},
            {"name": "C", "previous_brands": [{"brand": "Gymshark"}]},
        ],
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].weight == 0.20


def test_unit__search_2__matches_via_alias() -> None:
    bim = _brand_map(
        {"name": "Athletic Greens", "industry_id": "supplements-brands", "aliases": ["AG"]}
    )
    sources = search_2_similar_talent_brands.run(
        similar_talent=[{"name": "A", "previous_brands": [{"brand": "AG"}]}],
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "athletic-greens"


def test_unit__search_2__brand_not_in_seed_map_skipped() -> None:
    sources = search_2_similar_talent_brands.run(
        similar_talent=[{"name": "A", "previous_brands": [{"brand": "Obscure"}]}],
        brand_industry_map=_brand_map(),
    )
    assert sources == []


def test_unit__search_2__duplicate_mention_in_same_talent_counts_once() -> None:
    """Two mentions of the same brand in one similar talent should not double-count."""
    bim = _brand_map({"name": "Gymshark", "industry_id": "activewear"})
    sources = search_2_similar_talent_brands.run(
        similar_talent=[
            {"name": "A", "previous_brands": [{"brand": "Gymshark"}, {"brand": "Gymshark"}]}
        ],
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].weight == 0.10  # base, only 1 distinct mention


def test_unit__search_2__empty_similar_talent_returns_empty() -> None:
    sources = search_2_similar_talent_brands.run(
        similar_talent=[],
        brand_industry_map=_brand_map({"name": "Gymshark", "industry_id": "activewear"}),
    )
    assert sources == []
