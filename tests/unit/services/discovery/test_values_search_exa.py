"""M7.7 — Values-aligned Exa search tests (S13 v2)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.discovery._values_search import find_values_aligned_brands


def _mock_exa(brand_names: list[str]) -> MagicMock:
    exa = MagicMock()
    exa.search = AsyncMock(
        return_value={
            "results": [
                {
                    "url": f"https://example.com/{n}",
                    "title": f"{n} story",
                    "text": f"{n} is sustainable and female-founded.",
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
async def test_unit__values__no_themes_no_op() -> None:
    out = await find_values_aligned_brands(themes=[], industries=["toys"])
    assert out == []


@pytest.mark.asyncio
async def test_unit__values__no_industries_no_op() -> None:
    out = await find_values_aligned_brands(themes=["sustainable"], industries=[])
    assert out == []


@pytest.mark.asyncio
async def test_unit__values__theme_industry_combination() -> None:
    exa = _mock_exa(["Pact"])
    anth = _mock_anthropic(
        [
            {
                "brand_name": "Pact",
                "suggested_industry_id": "menswear-brands",
                "confidence": 0.92,
                "evidence": "Organic cotton + female-founded",
                "source_url": "https://example.com/Pact",
                "themes_matched": ["sustainable", "female-founded"],
            }
        ]
    )
    out = await find_values_aligned_brands(
        themes=["sustainable", "female-founded"],
        industries=["menswear-brands"],
        exa_client=exa,
        llm_client=anth,
    )
    # 2 themes x 1 industry x 1 result per query = 2 brand entries.
    assert len(out) == 2
    assert all(c["brand_name"] == "Pact" for c in out)
    assert all("themes_matched" in c for c in out)


@pytest.mark.asyncio
async def test_unit__values__low_confidence_dropped() -> None:
    exa = _mock_exa(["Weak"])
    anth = _mock_anthropic(
        [
            {
                "brand_name": "Weak",
                "suggested_industry_id": "toys",
                "confidence": 0.5,
                "evidence": "maybe",
            }
        ]
    )
    out = await find_values_aligned_brands(
        themes=["sustainable"], industries=["toys"], exa_client=exa, llm_client=anth
    )
    assert out == []
