"""M7.7 — Exa-based competitor search tests."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.discovery._competitor_search_exa import find_competitors


def _mock_exa(brand_names: list[str]) -> MagicMock:
    exa = MagicMock()
    exa.search = AsyncMock(
        return_value={
            "results": [
                {
                    "url": f"https://example.com/{n}",
                    "title": f"{n} story",
                    "text": f"{n} mentioned here as a competitor.",
                }
                for n in brand_names
            ]
        }
    )
    return exa


def _mock_anthropic(brands: list[dict[str, Any]]) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps({"competitors": brands})
    resp = MagicMock()
    resp.content = [block]
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_unit__competitor__finds_competitor_of_dunkin() -> None:
    exa = _mock_exa(["DoorDash"])
    anth = _mock_anthropic(
        [
            {
                "brand_name": "DoorDash",
                "confidence": 0.92,
                "evidence": "DoorDash competes with Dunkin' Donuts",
                "source_url": "https://example.com/DoorDash",
            }
        ]
    )
    out = await find_competitors(
        brand_name="Dunkin' Donuts",
        talent_country="US",
        exa_client=exa,
        llm_client=anth,
    )
    # 2 query variants → both return the same brand → 2 entries.
    assert len(out) == 2
    assert all(c["brand_name"] == "DoorDash" for c in out)
    # exa_query is tagged per result.
    queries = {c["exa_query"] for c in out}
    assert len(queries) == 2


@pytest.mark.asyncio
async def test_unit__competitor__low_confidence_dropped() -> None:
    exa = _mock_exa(["LowConf"])
    anth = _mock_anthropic([{"brand_name": "LowConf", "confidence": 0.5, "evidence": "weak"}])
    out = await find_competitors(brand_name="X", exa_client=exa, llm_client=anth)
    assert out == []


@pytest.mark.asyncio
async def test_unit__competitor__empty_brand_name_no_op() -> None:
    out = await find_competitors(brand_name="")
    assert out == []


@pytest.mark.asyncio
async def test_unit__competitor__exa_failure_recovered() -> None:
    """When Exa raises, we log + continue + return whatever we've got."""
    exa = MagicMock()
    exa.search = AsyncMock(side_effect=RuntimeError("upstream"))
    anth = _mock_anthropic([])
    out = await find_competitors(brand_name="X", exa_client=exa, llm_client=anth)
    assert out == []
