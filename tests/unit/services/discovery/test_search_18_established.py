"""M7.3 — Search 18 (established brands via Exa) — queries + extraction + run."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.discovery import search_18_established_brands

# ── Query builder ──────────────────────────────────────────────────


def test_unit__s18_queries__six_variations_per_industry() -> None:
    queries = search_18_established_brands._build_queries_for_industry("activewear")  # pyright: ignore[reportPrivateUsage]
    assert len(queries) == 6
    assert len(set(queries)) == 6


def test_unit__s18_queries__country_embedded_when_provided() -> None:
    queries = search_18_established_brands._build_queries_for_industry(  # pyright: ignore[reportPrivateUsage]
        "home-improvement", talent_country="US"
    )
    for q in queries:
        assert "US" in q
        assert "home improvement" in q


def test_unit__s18_queries__cover_top_best_dtc_creator_dimensions() -> None:
    """The 6 variations span the established-brand discovery angles."""
    queries = search_18_established_brands._build_queries_for_industry("toys")  # pyright: ignore[reportPrivateUsage]
    joined = " ".join(queries).lower()
    for keyword in ["top", "best", "d2c", "creator program", "established", "to watch"]:
        assert keyword in joined


# ── LLM extraction ─────────────────────────────────────────────────


def test_unit__s18_extract__strips_below_confidence_floor() -> None:
    high = (
        '{"brand_name": "BrandA", "suggested_industry_id": "toys", '
        '"confidence": 0.9, "evidence": "popular"}'
    )
    low = (
        '{"brand_name": "BrandB", "suggested_industry_id": "toys", '
        '"confidence": 0.65, "evidence": "weak"}'
    )
    raw_json = f'{{"brands": [{high},{low}]}}'
    out = search_18_established_brands._parse_llm_response(  # pyright: ignore[reportPrivateUsage]
        raw_json, fallback_industry_id="toys"
    )
    assert len(out) == 1
    assert out[0]["brand_name"] == "BrandA"


def test_unit__s18_extract__handles_invalid_json() -> None:
    out = search_18_established_brands._parse_llm_response(  # pyright: ignore[reportPrivateUsage]
        "not json", fallback_industry_id="toys"
    )
    assert out == []


# ── Full run ───────────────────────────────────────────────────────


def _mock_exa_search_response(brand_names: list[str]) -> dict[str, Any]:
    return {
        "results": [
            {
                "url": f"https://example.com/{n}",
                "title": f"Top {n} story",
                "text": f"{n} is a well-known established brand in the activewear industry.",
            }
            for n in brand_names
        ]
    }


def _mock_anthropic_response(brands: list[dict[str, Any]]) -> MagicMock:
    import json as _json

    response = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = _json.dumps({"brands": brands})
    response.content = [block]
    return response


@pytest.mark.asyncio
async def test_unit__search_18__happy_path_emits_established_tag() -> None:
    exa = MagicMock()
    exa.search = AsyncMock(return_value=_mock_exa_search_response(["Lululemon"]))

    anth = MagicMock()
    anth.messages.create = AsyncMock(
        return_value=_mock_anthropic_response(
            [
                {
                    "brand_name": "Lululemon",
                    "suggested_industry_id": "activewear",
                    "confidence": 0.92,
                    "evidence": "Listed in top 10 activewear brands.",
                }
            ]
        )
    )

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
    ):
        sources = await search_18_established_brands.run(
            top_industry_ids=["activewear"],
            brand_industry_map={"brands": []},
            talent_country="US",
            queries_per_industry=1,  # M7.5 — one query → one source
        )

    assert len(sources) == 1
    assert sources[0].brand_name == "Lululemon"
    assert sources[0].search_tag == "established_exa_discovery"
    assert 0.20 <= sources[0].weight <= 0.30
    # llm_confidence embedded for the qualifier.
    assert "llm_confidence=0.92" in sources[0].note


@pytest.mark.asyncio
async def test_unit__search_18__canonicalises_brands_already_in_seed_map() -> None:
    """M7.4 — Brands matching the seed map land on the canonical brand_id
    with a 'canonicalised from' note rather than being dropped."""
    exa = MagicMock()
    exa.search = AsyncMock(return_value=_mock_exa_search_response(["Nike"]))

    anth = MagicMock()
    anth.messages.create = AsyncMock(
        return_value=_mock_anthropic_response(
            [
                {
                    "brand_name": "Nike",
                    "suggested_industry_id": "sportswear",
                    "confidence": 0.95,
                    "evidence": "household name",
                }
            ]
        )
    )

    bim = {"brands": [{"brand_id": "nike", "name": "Nike", "industry_id": "sportswear"}]}

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
    ):
        sources = await search_18_established_brands.run(
            top_industry_ids=["sportswear"],
            brand_industry_map=bim,
            queries_per_industry=1,  # M7.5 — one query → one source
        )
    assert len(sources) == 1
    assert sources[0].brand_id == "nike"
    assert sources[0].brand_name == "Nike"


@pytest.mark.asyncio
async def test_unit__search_18__empty_industries_returns_empty() -> None:
    sources = await search_18_established_brands.run(
        top_industry_ids=[],
        brand_industry_map={"brands": []},
    )
    assert sources == []
