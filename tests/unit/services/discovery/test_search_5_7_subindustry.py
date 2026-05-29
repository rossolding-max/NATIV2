"""M7.3 — Search 5/6/7 sub-industry walk + weight decay."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.discovery import search_5_7_industry_tiers


def _tax_with_children(
    affinity_groups: list[dict[str, Any]],
    children_map: dict[str, list[str]],
) -> MagicMock:
    """Build a minimal Taxonomies mock with niche_industry_affinity + sub-industry mapping."""
    tax = MagicMock()
    tax.niche_industry_affinity = {"groups": affinity_groups}
    tax.get_sub_industries.side_effect = lambda industry_id: children_map.get(  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]
        industry_id, []
    )
    return tax


def _brand_map(brands: list[dict[str, Any]]) -> dict[str, Any]:
    return {"brands": brands}


def test_unit__sub_industry__parent_target_expands_to_children() -> None:
    """Target=sports-outdoor expands to its children + emits brands from each."""
    tax = _tax_with_children(
        affinity_groups=[{"niche_id": "fitness", "primary": ["sports-outdoor"]}],
        children_map={"sports-outdoor": ["sportswear", "outdoor-gear"]},
    )
    bim = _brand_map(
        [
            {"name": "Nike", "industry_id": "sportswear"},
            {"name": "Patagonia", "industry_id": "outdoor-gear"},
            {"name": "Sports Direct", "industry_id": "sports-outdoor"},
        ]
    )
    sources = search_5_7_industry_tiers.run(
        content_niches=["fitness"],
        tier="primary",
        taxonomies=tax,
        brand_industry_map=bim,
    )
    names = {s.brand_name for s in sources}
    assert names == {"Nike", "Patagonia", "Sports Direct"}


def test_unit__sub_industry__sub_industry_hits_get_decayed_weight() -> None:
    """Parent-target hits keep full weight; sub-industry hits get 0.8x."""
    tax = _tax_with_children(
        affinity_groups=[{"niche_id": "fitness", "primary": ["sports-outdoor"]}],
        children_map={"sports-outdoor": ["sportswear"]},
    )
    bim = _brand_map(
        [
            {"name": "Sports Direct", "industry_id": "sports-outdoor"},
            {"name": "Nike", "industry_id": "sportswear"},
        ]
    )
    sources = search_5_7_industry_tiers.run(
        content_niches=["fitness"],
        tier="primary",
        taxonomies=tax,
        brand_industry_map=bim,
    )
    by_name = {s.brand_name: s for s in sources}
    # Primary tier weight = 0.30; decay = 0.8 -> 0.24 for sub-industry hits.
    assert by_name["Sports Direct"].weight == 0.30
    assert by_name["Nike"].weight == 0.24
    assert "via sub-industry" in by_name["Nike"].note
    assert "via sub-industry" not in by_name["Sports Direct"].note


def test_unit__sub_industry__leaf_target_no_expansion() -> None:
    """When the target industry has no children, behaviour is the v0.1 single hit."""
    tax = _tax_with_children(
        affinity_groups=[{"niche_id": "fitness", "primary": ["sportswear"]}],
        children_map={},  # no sub-industries
    )
    bim = _brand_map(
        [
            {"name": "Nike", "industry_id": "sportswear"},
        ]
    )
    sources = search_5_7_industry_tiers.run(
        content_niches=["fitness"],
        tier="primary",
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_name == "Nike"
    assert sources[0].weight == 0.30


def test_unit__sub_industry__brand_listed_under_both_only_emits_once() -> None:
    """When a brand exists under BOTH the parent + a child industry, dedup
    keeps the parent hit (higher weight, emits first)."""
    tax = _tax_with_children(
        affinity_groups=[{"niche_id": "fitness", "primary": ["sports-outdoor"]}],
        children_map={"sports-outdoor": ["sportswear"]},
    )
    bim = _brand_map(
        [
            {"name": "Nike", "industry_id": "sports-outdoor"},  # parent
            {"name": "Nike Sub", "industry_id": "sportswear"},  # child (different name)
        ]
    )
    sources = search_5_7_industry_tiers.run(
        content_niches=["fitness"],
        tier="primary",
        taxonomies=tax,
        brand_industry_map=bim,
    )
    # Both unique brand_ids surface.
    assert {s.brand_name for s in sources} == {"Nike", "Nike Sub"}
    # Nike (parent hit) keeps full weight.
    nike = next(s for s in sources if s.brand_name == "Nike")
    assert nike.weight == 0.30


def test_unit__sub_industry__secondary_tier_weight_decay_applied() -> None:
    """Decay applies proportionally — secondary 0.20 * 0.8 = 0.16."""
    tax = _tax_with_children(
        affinity_groups=[{"niche_id": "fitness", "secondary": ["sports-outdoor"]}],
        children_map={"sports-outdoor": ["sportswear"]},
    )
    bim = _brand_map(
        [
            {"name": "Sports Direct", "industry_id": "sports-outdoor"},
            {"name": "Nike", "industry_id": "sportswear"},
        ]
    )
    sources = search_5_7_industry_tiers.run(
        content_niches=["fitness"],
        tier="secondary",
        taxonomies=tax,
        brand_industry_map=bim,
    )
    import pytest

    by_name = {s.brand_name: s for s in sources}
    assert by_name["Sports Direct"].weight == 0.20
    assert by_name["Nike"].weight == pytest.approx(0.16)
