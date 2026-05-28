"""Search 4 (competitors of brands that similar talents have worked with)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.discovery import search_4_competitors_of_similar


def _make_taxonomies(competitors: dict[str, list[str]]) -> MagicMock:
    tax = MagicMock()

    def _lookup(name: str) -> list[str]:
        return competitors.get(name, [])

    tax.get_competitors.side_effect = _lookup
    return tax


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def test_unit__search_4__competitor_of_similar_brand_emits_source() -> None:
    tax = _make_taxonomies({"Gymshark": ["Lululemon"]})
    bim = _brand_map({"name": "Lululemon", "industry_id": "activewear"})
    sources = search_4_competitors_of_similar.run(
        similar_talent=[{"name": "A", "previous_brands": [{"brand": "Gymshark"}]}],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "lululemon"
    assert sources[0].search_tag == "competitor_of_similar_talent"
    assert sources[0].weight == 0.10


def test_unit__search_4__dedupes_across_similar_talents() -> None:
    """Same competitor surfaced via multiple similar talents → one source."""
    tax = _make_taxonomies({"Gymshark": ["Nike"], "Adidas": ["Nike"]})
    bim = _brand_map({"name": "Nike", "industry_id": "sportswear"})
    sources = search_4_competitors_of_similar.run(
        similar_talent=[
            {"name": "A", "previous_brands": [{"brand": "Gymshark"}]},
            {"name": "B", "previous_brands": [{"brand": "Adidas"}]},
        ],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "nike"


def test_unit__search_4__competitor_not_in_seed_map_skipped() -> None:
    tax = _make_taxonomies({"Gymshark": ["UnknownBrand"]})
    sources = search_4_competitors_of_similar.run(
        similar_talent=[{"name": "A", "previous_brands": [{"brand": "Gymshark"}]}],
        taxonomies=tax,
        brand_industry_map=_brand_map(),
    )
    assert sources == []


def test_unit__search_4__no_similar_talent_returns_empty() -> None:
    tax = _make_taxonomies({})
    sources = search_4_competitors_of_similar.run(
        similar_talent=[],
        taxonomies=tax,
        brand_industry_map=_brand_map({"name": "Nike", "industry_id": "sportswear"}),
    )
    assert sources == []
