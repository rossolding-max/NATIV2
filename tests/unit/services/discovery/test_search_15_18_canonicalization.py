"""M7.4 — Search 15 / 18 brand canonicalization against the seed map."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.discovery import search_15_exa_newly_funded, search_18_established_brands


def _mock_exa(brand_names: list[str], industry: str) -> MagicMock:
    exa = MagicMock()
    exa.search = AsyncMock(
        return_value={
            "results": [
                {
                    "url": f"https://example.com/{n}",
                    "title": f"{n} story",
                    "text": f"{n} is a brand in {industry}.",
                }
                for n in brand_names
            ]
        }
    )
    return exa


def _mock_anthropic(brands: list[dict[str, Any]]) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps({"brands": brands})
    resp = MagicMock()
    resp.content = [block]
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_unit__s15__motor_company_canonicalises_to_ford() -> None:
    """Search 15 maps 'Ford Motor Company' Exa hit onto canonical 'Ford' seed entry."""
    exa = _mock_exa(["Ford Motor Company"], "auto-oems")
    anth = _mock_anthropic(
        [
            {
                "brand_name": "Ford Motor Company",
                "suggested_industry_id": "auto-oems",
                "confidence": 0.92,
                "evidence": "Top US auto.",
            }
        ]
    )
    seed = {"brands": [{"brand_id": "ford", "name": "Ford", "industry_id": "auto-oems"}]}

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
    ):
        sources = await search_15_exa_newly_funded.run(
            top_industry_ids=["auto-oems"],
            brand_industry_map=seed,
        )
    assert len(sources) == 1
    s = sources[0]
    assert s.brand_id == "ford"
    assert s.brand_name == "Ford"
    assert "canonicalised from 'Ford Motor Company'" in s.note


@pytest.mark.asyncio
async def test_unit__s18__motor_company_canonicalises_to_ford() -> None:
    """Search 18 mirrors the same canonicalization behaviour."""
    exa = _mock_exa(["General Motors"], "auto-oems")
    anth = _mock_anthropic(
        [
            {
                "brand_name": "General Motors",
                "suggested_industry_id": "auto-oems",
                "confidence": 0.92,
                "evidence": "Detroit big three.",
            }
        ]
    )
    seed = {
        "brands": [
            {
                "brand_id": "gm",
                "name": "GM",
                "industry_id": "auto-oems",
                "aliases": ["General Motors"],
            }
        ]
    }

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
    ):
        sources = await search_18_established_brands.run(
            top_industry_ids=["auto-oems"],
            brand_industry_map=seed,
        )
    assert len(sources) == 1
    s = sources[0]
    assert s.brand_id == "gm"
    assert s.brand_name == "GM"


@pytest.mark.asyncio
async def test_unit__s15__truly_net_new_brand_still_emits_as_net_new() -> None:
    """A brand that doesn't canonicalise remains a net-new emerging candidate."""
    exa = _mock_exa(["Kudos"], "diapers-nappies")
    anth = _mock_anthropic(
        [
            {
                "brand_name": "Kudos",
                "suggested_industry_id": "diapers-nappies",
                "confidence": 0.92,
                "evidence": "Series A in 2026.",
            }
        ]
    )
    seed = {"brands": []}

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
    ):
        sources = await search_15_exa_newly_funded.run(
            top_industry_ids=["diapers-nappies"],
            brand_industry_map=seed,
        )
    assert len(sources) == 1
    assert sources[0].brand_id == "kudos"
    assert "canonicalised from" not in sources[0].note
