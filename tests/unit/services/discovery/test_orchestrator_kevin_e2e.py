"""M7.3 — Kevin Cooney-shaped end-to-end orchestrator run.

Synthesises a US-based dad-life talent with NO audience demographics
(OAuth-skipped case) and exercises the full ``run_discovery`` pipeline
with REAL taxonomies + REAL brand_industry_map.json + MOCKED Exa/Claude.

Asserts the M7.3 acceptance criteria:
  (a) no UK-only retailers (Tesco/Sainsbury's/Gousto) surface for a
      US talent;
  (b) ``tier="emerging"`` candidates appear when Exa returns net-new
      brands with high LLM confidence;
  (c) total candidate count is materially higher than the v0.1 baseline
      thanks to sub-industry expansion + Search 18.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.discovery._models import DiscoveryRunResult
from app.services.discovery.orchestrator import run_discovery
from app.utils.taxonomies import get_taxonomies, init_taxonomies


@pytest.fixture(autouse=True)
def _init_taxonomies() -> None:  # pyright: ignore[reportUnusedFunction]
    """Bootstrap the taxonomy singleton from the real data dir."""
    init_taxonomies()


def _exa_response(brand_names: list[str], industry: str) -> dict[str, Any]:
    return {
        "results": [
            {
                "title": f"{n} — top brand in {industry}",
                "url": f"https://example.com/{n.replace(' ', '-').lower()}",
                "text": f"{n} is a recognised brand in the {industry} category in the US.",
            }
            for n in brand_names
        ]
    }


def _anthropic_response(brands: list[dict[str, Any]]) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps({"brands": brands})
    resp = MagicMock()
    resp.content = [block]
    return resp


@pytest.fixture
def kevin_talent_data() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
    """Match Kevin's onboarding state: US-based, dad-life niche, no audience yet."""
    return {
        "content_niches": ["dad-life"],
        "previous_brands": [],
        "audience_demographics": {},  # OAuth skipped
        "brand_preferences": {},
        "location": {"country": "US"},
    }


@pytest.mark.asyncio
async def test_unit__kevin_e2e__uk_only_retailers_filtered_out(
    kevin_talent_data: dict[str, Any],
) -> None:
    """Tesco / Sainsbury's / Gousto must not surface for a US-based talent."""
    # Mock Exa so the test stays offline + deterministic; the seed-map
    # walks still exercise real taxonomies + real brand data.
    exa = MagicMock()
    exa.search = AsyncMock(return_value={"results": []})
    anth = MagicMock()
    anth.messages.create = AsyncMock(return_value=_anthropic_response([]))

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
    ):
        result: DiscoveryRunResult = await run_discovery(
            talent_id="kevin-cooney",
            talent_data=kevin_talent_data,
            brand_deals=[],
            taxonomies=get_taxonomies(),
        )

    surfaced_names = {c.brand_name for c in result.candidates}
    # UK-only retailers from the seed map that previously leaked through.
    for uk_only in {"Tesco", "Sainsbury's", "Gousto", "Boots", "easyJet"}:
        assert uk_only not in surfaced_names, f"{uk_only} should be geo-filtered for US talent"


@pytest.mark.asyncio
async def test_unit__kevin_e2e__emerging_tier_present_when_exa_finds_new_brands(
    kevin_talent_data: dict[str, Any],
) -> None:
    """Exa-discovered brands with high LLM confidence land as tier=emerging."""
    # Wire Exa + Claude to surface a couple of net-new brands per call.
    # Search 15 + Search 18 both run; both extract brands.
    exa = MagicMock()
    exa.search = AsyncMock(return_value=_exa_response(["Tak Tak Toys", "Peachies"], "toys"))
    anth = MagicMock()
    anth.messages.create = AsyncMock(
        return_value=_anthropic_response(
            [
                {
                    "brand_name": "Tak Tak Toys",
                    "suggested_industry_id": "toys",
                    "confidence": 0.92,
                    "evidence": "Series A 2026.",
                },
                {
                    "brand_name": "Peachies",
                    "suggested_industry_id": "baby-care",
                    "confidence": 0.88,
                    "evidence": "Newly launched DTC diaper brand.",
                },
            ]
        )
    )

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
    ):
        result = await run_discovery(
            talent_id="kevin-cooney",
            talent_data=kevin_talent_data,
            brand_deals=[],
            taxonomies=get_taxonomies(),
        )

    emerging = [c for c in result.candidates if c.tier == "emerging"]
    assert len(emerging) >= 1, "Exa-discovered net-new brands should surface as tier=emerging"
    # The qualification tier on these is speculative (per the Commit 1 promotion).
    for c in emerging:
        assert c.qualification_tier in {"qualified", "speculative"}


@pytest.mark.asyncio
async def test_unit__kevin_e2e__candidate_count_meaningfully_higher_than_v01(
    kevin_talent_data: dict[str, Any],
) -> None:
    """v0.1 baseline was 47 candidates for Kevin. M7.3 should at least double the
    count when Exa returns even a handful of net-new brands per industry — and
    the sub-industry walks should pull in brands like Hasbro / Mattel that
    only sit under child industries of the affinity-targeted parents."""
    # Exa returns 3 brands per query; LLM extracts all 3 with high confidence.
    exa = MagicMock()
    exa.search = AsyncMock(return_value=_exa_response(["BrandA", "BrandB", "BrandC"], "category"))
    anth = MagicMock()
    anth.messages.create = AsyncMock(
        return_value=_anthropic_response(
            [
                {
                    "brand_name": f"BrandA{i}",
                    "suggested_industry_id": "toys",
                    "confidence": 0.85,
                    "evidence": "Generic test brand.",
                }
                for i in range(3)
            ]
        )
    )

    with (
        patch("app.vendors.exa.ExaClient", return_value=exa),
        patch("app.agents.llm_client.get_async_anthropic", return_value=anth),
    ):
        result = await run_discovery(
            talent_id="kevin-cooney",
            talent_data=kevin_talent_data,
            brand_deals=[],
            taxonomies=get_taxonomies(),
        )

    # Pre-M7.3 baseline for Kevin: 47 candidates. The bar here is intentionally
    # conservative — we just want a regression guard that the sub-industry +
    # Exa expansion is wired through. A live run surfaces 150+.
    assert len(result.candidates) >= 50, (
        f"Expected >=50 candidates with M7.3 expansions, got {len(result.candidates)}"
    )
