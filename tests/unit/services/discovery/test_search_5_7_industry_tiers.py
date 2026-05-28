"""Searches 5 / 6 / 7 (niche -> tiered-industry -> brands)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.discovery import search_5_7_industry_tiers


def _make_taxonomies(affinity_groups: list[dict[str, Any]]) -> MagicMock:
    tax = MagicMock()
    tax.niche_industry_affinity = {"groups": affinity_groups}
    return tax


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def test_unit__primary_tier_emits_brands_at_weight_0_30() -> None:
    tax = _make_taxonomies([{"niche_id": "beauty", "primary": ["cosmetics"]}])
    bim = _brand_map(
        {"name": "MAC", "industry_id": "cosmetics"},
        {"name": "Adidas", "industry_id": "sportswear"},
    )
    sources = search_5_7_industry_tiers.run(
        content_niches=["beauty"],
        tier="primary",
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "mac"
    assert sources[0].weight == 0.30
    assert sources[0].search_tag == "primary_industry"


def test_unit__secondary_tier_weight_is_0_20() -> None:
    tax = _make_taxonomies([{"niche_id": "beauty", "secondary": ["jewellery"]}])
    bim = _brand_map({"name": "Tiffany", "industry_id": "jewellery"})
    sources = search_5_7_industry_tiers.run(
        content_niches=["beauty"],
        tier="secondary",
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].weight == 0.20


def test_unit__tertiary_tier_weight_is_0_06() -> None:
    tax = _make_taxonomies([{"niche_id": "beauty", "tertiary": ["telehealth"]}])
    bim = _brand_map({"name": "Hims", "industry_id": "telehealth"})
    sources = search_5_7_industry_tiers.run(
        content_niches=["beauty"],
        tier="tertiary",
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].weight == 0.06


def test_unit__dedupes_brands_across_niches() -> None:
    """If two niches share a primary industry, a brand in it only emits once."""
    tax = _make_taxonomies(
        [
            {"niche_id": "beauty", "primary": ["cosmetics"]},
            {"niche_id": "lifestyle", "primary": ["cosmetics"]},
        ]
    )
    bim = _brand_map({"name": "MAC", "industry_id": "cosmetics"})
    sources = search_5_7_industry_tiers.run(
        content_niches=["beauty", "lifestyle"],
        tier="primary",
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1


def test_unit__niche_not_in_affinity_emits_nothing() -> None:
    tax = _make_taxonomies([{"niche_id": "fitness", "primary": ["activewear"]}])
    bim = _brand_map({"name": "Gymshark", "industry_id": "activewear"})
    sources = search_5_7_industry_tiers.run(
        content_niches=["unknown-niche"],
        tier="primary",
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert sources == []


def test_unit__invalid_tier_returns_empty() -> None:
    tax = _make_taxonomies([{"niche_id": "beauty", "primary": ["cosmetics"]}])
    bim = _brand_map({"name": "MAC", "industry_id": "cosmetics"})
    sources = search_5_7_industry_tiers.run(
        content_niches=["beauty"],
        tier="invalid-tier",  # type: ignore[arg-type]
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert sources == []
