"""M7.6 — Social handle enrichment via 2-Exa-call follow-up."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.discovery._social_enrichment import (
    enrich_extracted_brands_inplace,
    enrich_social_handles,
)


def _mock_exa(results: list[dict[str, Any]]) -> MagicMock:
    exa = MagicMock()
    exa.search = AsyncMock(return_value={"results": results})
    return exa


def _multi_response_exa(responses: list[list[dict[str, Any]]]) -> MagicMock:
    """An ExaClient whose search() returns each response list once, in order."""
    exa = MagicMock()
    exa.search = AsyncMock(side_effect=[{"results": r} for r in responses])
    return exa


@pytest.mark.asyncio
async def test_unit__enrich_handles__finds_ig_from_url() -> None:
    exa = _mock_exa(
        [{"url": "https://www.instagram.com/hellokudos", "title": "Kudos on Instagram"}]
    )
    out = await enrich_social_handles(
        brand_name="Kudos", needs_instagram=True, needs_tiktok=False, exa_client=exa
    )
    assert out["instagram"] == "@hellokudos"
    assert out["tiktok"] is None


@pytest.mark.asyncio
async def test_unit__enrich_handles__finds_tiktok_from_url() -> None:
    exa = _mock_exa(
        [{"url": "https://www.tiktok.com/@kudosdiapers", "title": "Kudos TikTok"}]
    )
    out = await enrich_social_handles(
        brand_name="Kudos", needs_instagram=False, needs_tiktok=True, exa_client=exa
    )
    assert out["tiktok"] == "@kudosdiapers"


@pytest.mark.asyncio
async def test_unit__enrich_handles__skips_post_urls() -> None:
    """instagram.com/p/<id> is a post, not a handle. Should not match."""
    exa = _mock_exa(
        [{"url": "https://www.instagram.com/p/AbCdEf/", "title": "A post"}]
    )
    out = await enrich_social_handles(
        brand_name="X", needs_instagram=True, needs_tiktok=False, exa_client=exa
    )
    assert out["instagram"] is None


@pytest.mark.asyncio
async def test_unit__enrich_handles__no_results_returns_nulls() -> None:
    exa = _mock_exa([])
    out = await enrich_social_handles(
        brand_name="X", needs_instagram=True, needs_tiktok=True, exa_client=exa
    )
    assert out == {"instagram": None, "tiktok": None}


@pytest.mark.asyncio
async def test_unit__enrich_handles__needs_both_fires_two_searches() -> None:
    exa = _multi_response_exa(
        [
            [{"url": "https://www.instagram.com/kudos"}],
            [{"url": "https://www.tiktok.com/@kudostt"}],
        ]
    )
    out = await enrich_social_handles(
        brand_name="Kudos", needs_instagram=True, needs_tiktok=True, exa_client=exa
    )
    assert out["instagram"] == "@kudos"
    assert out["tiktok"] == "@kudostt"
    assert exa.search.call_count == 2


@pytest.mark.asyncio
async def test_unit__enrich_inplace__skips_brand_already_in_seed_map() -> None:
    """A brand whose seed entry already has IG should not fire enrichment."""
    extracted: list[dict[str, Any]] = [
        {
            "brand_name": "Kudos",
            "social_handles": {"instagram": None, "tiktok": None},
        }
    ]
    seed_brands: list[dict[str, Any]] = [
        {"name": "Kudos", "social_handles": {"instagram": "@hellokudos", "tiktok": "@kudos"}},
    ]
    exa = MagicMock()
    exa.search = AsyncMock(side_effect=AssertionError("should not be called"))
    await enrich_extracted_brands_inplace(extracted, seed_brands, exa_client=exa)
    assert exa.search.call_count == 0
    # Handles propagated from the seed map.
    handles = extracted[0]["social_handles"]
    assert isinstance(handles, dict)
    assert handles["instagram"] == "@hellokudos"


@pytest.mark.asyncio
async def test_unit__enrich_inplace__fires_when_neither_extraction_nor_seed_has_handle() -> None:
    extracted: list[dict[str, Any]] = [
        {
            "brand_name": "Kudos",
            "social_handles": {"instagram": None, "tiktok": None},
        }
    ]
    seed_brands: list[dict[str, Any]] = []  # not in seed
    exa = _multi_response_exa(
        [
            [{"url": "https://www.instagram.com/kudoshello"}],
            [{"url": "https://www.tiktok.com/@kudoshello"}],
        ]
    )
    await enrich_extracted_brands_inplace(extracted, seed_brands, exa_client=exa)
    handles = extracted[0]["social_handles"]
    assert isinstance(handles, dict)
    assert handles["instagram"] == "@kudoshello"
    assert handles["tiktok"] == "@kudoshello"


@pytest.mark.asyncio
async def test_unit__enrich_inplace__dedup_across_multiple_hits_same_brand() -> None:
    """Two extracted entries for the same brand should produce one enrichment call pair."""
    extracted: list[dict[str, Any]] = [
        {
            "brand_name": "Kudos",
            "exa_query": "query_a",
            "social_handles": {"instagram": None, "tiktok": None},
        },
        {
            "brand_name": "Kudos",
            "exa_query": "query_b",
            "social_handles": {"instagram": None, "tiktok": None},
        },
    ]
    exa = _multi_response_exa(
        [
            [{"url": "https://www.instagram.com/kudos"}],
            [{"url": "https://www.tiktok.com/@kudos"}],
        ]
    )
    await enrich_extracted_brands_inplace(extracted, [], exa_client=exa)
    # Only 2 Exa calls total — one IG + one TikTok for the unique brand.
    assert exa.search.call_count == 2
    # Both hits share the enriched handles.
    h0 = extracted[0]["social_handles"]
    h1 = extracted[1]["social_handles"]
    assert isinstance(h0, dict)
    assert isinstance(h1, dict)
    assert h0["instagram"] == "@kudos"
    assert h1["instagram"] == "@kudos"
