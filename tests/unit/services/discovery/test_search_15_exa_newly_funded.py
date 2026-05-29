"""Search 15 (Exa-driven newly-funded brands) — mocked Exa + Claude."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.discovery import search_15_exa_newly_funded


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


def _mock_exa_search_response(brand_names: list[str]) -> dict[str, Any]:
    """Shape mirrors what ExaClient.search returns."""
    return {
        "results": [
            {
                "title": f"{name} raised $X",
                "url": f"https://example.com/{name.lower()}",
                "text": f"{name} is a newly funded brand in the activewear space.",
            }
            for name in brand_names
        ]
    }


def _mock_llm_response(brand_extractions: list[dict[str, Any]]) -> MagicMock:
    """Shape mirrors anthropic SDK ``messages.create`` return."""
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps({"brands": brand_extractions})
    resp = MagicMock()
    resp.content = [block]
    return resp


@pytest.mark.asyncio
async def test_unit__search_15__happy_path_extracts_new_brand() -> None:
    exa = MagicMock()
    exa.search = AsyncMock(return_value=_mock_exa_search_response(["Alo Yoga"]))
    anthropic = MagicMock()
    anthropic.messages.create = AsyncMock(
        return_value=_mock_llm_response(
            [
                {
                    "brand_name": "Alo Yoga",
                    "suggested_industry_id": "activewear",
                    "confidence": 0.90,
                    "evidence": "Series B raised in 2026.",
                }
            ]
        )
    )

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anthropic),
    ):
        sources = await search_15_exa_newly_funded.run(
            top_industry_ids=["activewear"],
            brand_industry_map=_brand_map(),
            max_industries=1,
            queries_per_industry=1,
            results_per_query=1,
        )

    assert len(sources) == 1
    assert sources[0].brand_id == "alo-yoga"
    assert sources[0].industry_id == "activewear"
    assert sources[0].search_tag == "recently_funded"
    # M7.3 — weight scales with confidence in the 0.20-0.30 range
    # (bumped from 0.10-0.15 to clear the qualification noise floor).
    assert 0.20 <= sources[0].weight <= 0.30
    # M7.3 — the note embeds llm_confidence for the qualifier to read.
    assert "llm_confidence=" in sources[0].note


@pytest.mark.asyncio
async def test_unit__search_15__existing_brand_in_seed_map_skipped() -> None:
    """A brand already in brand_industry_map shouldn't be emitted as net-new."""
    exa = MagicMock()
    exa.search = AsyncMock(return_value=_mock_exa_search_response(["Gymshark"]))
    anthropic = MagicMock()
    anthropic.messages.create = AsyncMock(
        return_value=_mock_llm_response(
            [
                {
                    "brand_name": "Gymshark",
                    "suggested_industry_id": "activewear",
                    "confidence": 0.95,
                    "evidence": "Series C.",
                }
            ]
        )
    )
    seed = _brand_map({"name": "Gymshark", "industry_id": "activewear"})

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anthropic),
    ):
        sources = await search_15_exa_newly_funded.run(
            top_industry_ids=["activewear"],
            brand_industry_map=seed,
        )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_15__low_confidence_dropped() -> None:
    exa = MagicMock()
    exa.search = AsyncMock(return_value=_mock_exa_search_response(["UnknownBrand"]))
    anthropic = MagicMock()
    anthropic.messages.create = AsyncMock(
        return_value=_mock_llm_response(
            [
                {
                    "brand_name": "UnknownBrand",
                    "suggested_industry_id": "activewear",
                    "confidence": 0.50,
                    "evidence": "Maybe a brand?",
                }
            ]
        )
    )

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anthropic),
    ):
        sources = await search_15_exa_newly_funded.run(
            top_industry_ids=["activewear"],
            brand_industry_map=_brand_map(),
        )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_15__no_industries_returns_empty() -> None:
    sources = await search_15_exa_newly_funded.run(
        top_industry_ids=[],
        brand_industry_map=_brand_map(),
    )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_15__llm_returns_non_json_returns_empty() -> None:
    exa = MagicMock()
    exa.search = AsyncMock(return_value=_mock_exa_search_response(["X"]))
    anthropic = MagicMock()
    block = MagicMock()
    block.type = "text"
    block.text = "I'm sorry, I can't help with that."
    resp = MagicMock()
    resp.content = [block]
    anthropic.messages.create = AsyncMock(return_value=resp)

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anthropic),
    ):
        sources = await search_15_exa_newly_funded.run(
            top_industry_ids=["activewear"],
            brand_industry_map=_brand_map(),
        )
    assert sources == []


@pytest.mark.asyncio
async def test_unit__search_15__exa_failure_does_not_kill_run() -> None:
    """If Exa raises, the search returns empty rather than blowing up the orchestrator."""
    exa = MagicMock()
    exa.search = AsyncMock(side_effect=RuntimeError("upstream-failed"))
    anthropic = MagicMock()
    anthropic.messages.create = AsyncMock(return_value=_mock_llm_response([]))

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anthropic),
    ):
        sources = await search_15_exa_newly_funded.run(
            top_industry_ids=["activewear"],
            brand_industry_map=_brand_map(),
        )
    assert sources == []
