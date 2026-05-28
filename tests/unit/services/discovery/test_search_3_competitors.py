"""Search 3 (competitors of previous brands)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.discovery import search_3_competitors


def _make_taxonomies(competitors: dict[str, list[str]]) -> MagicMock:
    tax = MagicMock()

    def _lookup(name: str) -> list[str]:
        return competitors.get(name, [])

    tax.get_competitors.side_effect = _lookup
    return tax


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def test_unit__search_3__competitor_in_seed_map_emits_source() -> None:
    tax = _make_taxonomies({"Gymshark": ["Lululemon"]})
    bim = _brand_map(
        {"name": "Lululemon", "industry_id": "activewear"},
    )
    sources = search_3_competitors.run(
        previous_brands=[{"brand": "Gymshark"}],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "lululemon"
    assert sources[0].search_tag == "competitor_of_previous"
    assert sources[0].weight == 0.25


def test_unit__search_3__competitor_not_in_seed_map_skipped() -> None:
    tax = _make_taxonomies({"Gymshark": ["UnknownBrand"]})
    sources = search_3_competitors.run(
        previous_brands=[{"brand": "Gymshark"}],
        taxonomies=tax,
        brand_industry_map=_brand_map(),
    )
    assert sources == []


def test_unit__search_3__dedupes_across_past_brands() -> None:
    """If two past brands share a competitor, only one source emits."""
    tax = _make_taxonomies({"Gymshark": ["Nike"], "Adidas": ["Nike"]})
    bim = _brand_map({"name": "Nike", "industry_id": "sportswear"})
    sources = search_3_competitors.run(
        previous_brands=[{"brand": "Gymshark"}, {"brand": "Adidas"}],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "nike"


def test_unit__search_3__matches_via_alias() -> None:
    """If the competitor's name doesn't match a brand but an alias does, still emit."""
    tax = _make_taxonomies({"Gymshark": ["AG"]})
    bim = _brand_map(
        {"name": "Athletic Greens", "industry_id": "supplements-brands", "aliases": ["AG"]}
    )
    sources = search_3_competitors.run(
        previous_brands=[{"brand": "Gymshark"}],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "athletic-greens"


def test_unit__search_3__missing_industry_id_skipped() -> None:
    tax = _make_taxonomies({"Gymshark": ["Lululemon"]})
    bim = _brand_map({"name": "Lululemon"})  # no industry_id
    sources = search_3_competitors.run(
        previous_brands=[{"brand": "Gymshark"}],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert sources == []
