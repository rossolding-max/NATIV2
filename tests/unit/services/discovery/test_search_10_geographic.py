"""Search 10 (geographic alignment)."""

from __future__ import annotations

from typing import Any

from app.services.discovery import search_10_geographic


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def test_unit__hq_match_emits_high_weight() -> None:
    bim = _brand_map(
        {"name": "MAC", "industry_id": "cosmetics", "hq_country": "US"},
    )
    sources = search_10_geographic.run(
        audience_demographics={"top_countries": ["US"]},
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].weight == 0.08
    assert sources[0].search_tag == "geographic_alignment"


def test_unit__sells_in_match_emits_lower_weight() -> None:
    bim = _brand_map(
        {"name": "MAC", "industry_id": "cosmetics", "hq_country": "FR", "sells_in_countries": "US"},
    )
    sources = search_10_geographic.run(
        audience_demographics={"top_countries": ["US"]},
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    assert sources[0].weight == 0.04


def test_unit__global_sells_in_matches() -> None:
    bim = _brand_map(
        {
            "name": "Nike",
            "industry_id": "sportswear",
            "hq_country": "US",
            "sells_in_countries": "global",
        },
    )
    sources = search_10_geographic.run(
        audience_demographics={"top_countries": ["GB"]},
        brand_industry_map=bim,
    )
    assert len(sources) == 1
    # HQ doesn't match GB; global sells_in catches the audience.
    assert sources[0].weight == 0.04


def test_unit__no_audience_countries_returns_empty() -> None:
    bim = _brand_map({"name": "Nike", "industry_id": "sportswear", "hq_country": "US"})
    sources = search_10_geographic.run(
        audience_demographics={},
        brand_industry_map=bim,
    )
    assert sources == []


def test_unit__country_list_can_be_dict_or_string() -> None:
    bim = _brand_map({"name": "MAC", "industry_id": "cosmetics", "hq_country": "US"})
    sources = search_10_geographic.run(
        audience_demographics={"top_countries": [{"country": "US"}, "GB"]},
        brand_industry_map=bim,
    )
    assert len(sources) == 1
