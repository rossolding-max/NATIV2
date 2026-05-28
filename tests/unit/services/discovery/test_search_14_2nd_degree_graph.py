"""Search 14 (2nd-degree competitor graph expansion)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.discovery import search_14_2nd_degree_graph


def _make_taxonomies(competitors: dict[str, list[str]]) -> MagicMock:
    tax = MagicMock()

    def _lookup(name: str) -> list[str]:
        return competitors.get(name, [])

    tax.get_competitors.side_effect = _lookup
    return tax


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def test_unit__search_14__second_hop_competitor_emits_source() -> None:
    """Gymshark -> Nike -> Adidas: Adidas surfaces at 2nd-degree."""
    tax = _make_taxonomies({"Gymshark": ["Nike"], "Nike": ["Adidas"]})
    bim = _brand_map({"name": "Adidas", "industry_id": "sportswear"})
    sources = search_14_2nd_degree_graph.run(
        previous_brands=[{"brand": "Gymshark"}],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "adidas"
    assert sources[0].search_tag == "graph_expansion_2nd_degree"
    assert sources[0].weight == 0.03


def test_unit__search_14__first_hop_excluded_to_avoid_double_count() -> None:
    """Search 3 already surfaces Nike (direct competitor of Gymshark) so Search 14
    must NOT also surface Nike via the second hop."""
    tax = _make_taxonomies({"Gymshark": ["Nike", "Adidas"], "Nike": ["Adidas"], "Adidas": ["Nike"]})
    bim = _brand_map(
        {"name": "Nike", "industry_id": "sportswear"},
        {"name": "Adidas", "industry_id": "sportswear"},
    )
    sources = search_14_2nd_degree_graph.run(
        previous_brands=[{"brand": "Gymshark"}],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    # Both Nike and Adidas are 1st-hop competitors of Gymshark.
    assert sources == []


def test_unit__search_14__original_brand_excluded() -> None:
    """Talent worked with Gymshark; if the graph circles back, Gymshark must not surface."""
    tax = _make_taxonomies({"Gymshark": ["Nike"], "Nike": ["Gymshark"]})
    bim = _brand_map(
        {"name": "Nike", "industry_id": "sportswear"},
        {"name": "Gymshark", "industry_id": "activewear"},
    )
    sources = search_14_2nd_degree_graph.run(
        previous_brands=[{"brand": "Gymshark"}],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert sources == []


def test_unit__search_14__second_hop_dedupes() -> None:
    """Two different first-hop paths converging on same 2nd-degree brand -> one source."""
    tax = _make_taxonomies(
        {
            "Gymshark": ["Nike", "Lululemon"],
            "Nike": ["Adidas"],
            "Lululemon": ["Adidas"],
        }
    )
    bim = _brand_map(
        {"name": "Adidas", "industry_id": "sportswear"},
    )
    sources = search_14_2nd_degree_graph.run(
        previous_brands=[{"brand": "Gymshark"}],
        taxonomies=tax,
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].brand_id == "adidas"


def test_unit__search_14__second_hop_not_in_seed_map_skipped() -> None:
    tax = _make_taxonomies({"Gymshark": ["Nike"], "Nike": ["UnknownBrand"]})
    sources = search_14_2nd_degree_graph.run(
        previous_brands=[{"brand": "Gymshark"}],
        taxonomies=tax,
        brand_industry_map=_brand_map({"name": "Nike", "industry_id": "sportswear"}),
    )
    assert sources == []


def test_unit__search_14__no_previous_brands_returns_empty() -> None:
    tax = _make_taxonomies({})
    sources = search_14_2nd_degree_graph.run(
        previous_brands=[],
        taxonomies=tax,
        brand_industry_map=_brand_map({"name": "Nike", "industry_id": "sportswear"}),
    )
    assert sources == []
