"""M7.7 — Phase 4 signal-overlay tests."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.discovery import phase_4_signal_overlay as p4


def _mock_exa(brand_names: list[str]) -> MagicMock:
    exa = MagicMock()
    exa.search = AsyncMock(
        return_value={
            "results": [
                {
                    "url": f"https://example.com/{n}",
                    "title": n,
                    "text": f"{n} just raised a round.",
                }
                for n in brand_names
            ]
        }
    )
    return exa


def _mock_anth(brands: list[dict[str, Any]]) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps({"brands": brands})
    resp = MagicMock()
    resp.content = [block]
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=resp)
    return client


# ── _global_trending_funded_queries ────────────────────────────


def test_unit__p4_queries__seven_global_variants() -> None:
    qs = p4._global_trending_funded_queries(talent_country="US")  # pyright: ignore[reportPrivateUsage]
    assert len(qs) == 7
    assert all("US" in q for q in qs)


def test_unit__p4_queries__country_optional() -> None:
    qs = p4._global_trending_funded_queries(talent_country=None)  # pyright: ignore[reportPrivateUsage]
    assert len(qs) == 7
    # no double-spaces from missing geo
    for q in qs:
        assert "  " not in q


# ── _exa_global_funded ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_unit__p4_global_funded__emits_global_trending_tag() -> None:
    exa = _mock_exa(["Kudos"])
    anth = _mock_anth(
        [
            {
                "brand_name": "Kudos",
                "suggested_industry_id": "diapers-nappies",
                "confidence": 0.88,
                "evidence": "Series A 2026.",
                "source_url": "https://example.com/Kudos",
            }
        ]
    )
    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
    ):
        sources = await p4._exa_global_funded(talent_country="US", results_per_query=1)  # pyright: ignore[reportPrivateUsage]
    assert all(s.search_tag == "global_trending_funded" for s in sources)
    # Multiple queries → multiple sources for the same brand.
    assert len(sources) >= 1
    for s in sources:
        assert s.exa_query is not None


# ── run() composition ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_unit__p4_run__s16_s17_gated_off_by_default() -> None:
    """With both flags off, only S15-residual fires."""
    exa = _mock_exa([])
    anth = _mock_anth([])
    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
    ):
        sources = await p4.run(
            talent_data={},
            taxonomies=MagicMock(),
            brand_industry_map={"brands": []},
            talent_country="US",
        )
    # No S16/S17 (gated off in default settings); S15-global got no brands.
    assert sources == []


@pytest.mark.asyncio
async def test_unit__p4_run__s15_disable_skips_global_call() -> None:
    """Setting s15_global_enabled=False prevents the global trending sweep."""
    exa = MagicMock()
    exa.search = AsyncMock(side_effect=AssertionError("should not be called"))
    with patch("app.vendors.exa.ExaClient", return_value=exa):
        sources = await p4.run(
            talent_data={},
            taxonomies=MagicMock(),
            brand_industry_map={"brands": []},
            talent_country="US",
            s15_global_enabled=False,
        )
    assert sources == []
    exa.search.assert_not_called()
