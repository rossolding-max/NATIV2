"""M7.7 — Phase 3 talent-specific composition tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services.discovery import phase_3_talent_specific as p3


def _bim(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


@pytest.mark.asyncio
async def test_unit__p3__empty_talent_returns_empty() -> None:
    sources = await p3.run(
        talent_data={"previous_brands": [], "similar_talent": []},
        brand_deals=[],
        brand_industry_map=_bim(),
    )
    # S1/S2 return [] for empty inputs; S3/S4 are not called when no brands; S13 off.
    assert sources == []


@pytest.mark.asyncio
async def test_unit__p3__exa_competitors_fire_for_each_past_brand() -> None:
    talent_data = {
        "previous_brands": [
            {"brand": "Dunkin' Donuts", "industry_id": "restaurants-qsr"},
            {"brand": "CVS", "industry_id": "drug-stores"},
        ],
        "similar_talent": [],
    }
    # Mock _exa_competitors_for_previous to return a fixed source per call.
    with patch(
        "app.services.discovery.phase_3_talent_specific._exa_competitors_for_previous",
        new=AsyncMock(return_value=[]),
    ) as mock_s3:
        await p3.run(
            talent_data=talent_data,
            brand_deals=[],
            brand_industry_map=_bim(),
            talent_country="US",
        )
        mock_s3.assert_called_once()


@pytest.mark.asyncio
async def test_unit__p3__values_search_only_when_enabled() -> None:
    """S13 fires only when values_search_enabled AND values_aligned_themes exist."""
    talent_data = {
        "brand_preferences": {"values_aligned_themes": ["sustainable"]},
        "previous_brands": [],
        "similar_talent": [],
    }
    with patch(
        "app.services.discovery.phase_3_talent_specific._exa_values_aligned",
        new=AsyncMock(return_value=[]),
    ) as mock_s13:
        # Disabled → no call.
        await p3.run(
            talent_data=talent_data,
            brand_deals=[],
            brand_industry_map=_bim(),
            approved_industries=["toys"],
            values_search_enabled=False,
        )
        mock_s13.assert_not_called()

        # Enabled + themes + industries → fires.
        await p3.run(
            talent_data=talent_data,
            brand_deals=[],
            brand_industry_map=_bim(),
            approved_industries=["toys"],
            values_search_enabled=True,
        )
        mock_s13.assert_called_once()


@pytest.mark.asyncio
async def test_unit__p3__values_search_skipped_without_industries() -> None:
    """Even when enabled, S13 needs approved_industries — empty list → no-op."""
    talent_data = {
        "brand_preferences": {"values_aligned_themes": ["sustainable"]},
        "previous_brands": [],
        "similar_talent": [],
    }
    with patch(
        "app.services.discovery.phase_3_talent_specific._exa_values_aligned",
        new=AsyncMock(return_value=[]),
    ) as mock_s13:
        await p3.run(
            talent_data=talent_data,
            brand_deals=[],
            brand_industry_map=_bim(),
            approved_industries=[],
            values_search_enabled=True,
        )
        mock_s13.assert_not_called()
