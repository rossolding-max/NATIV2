"""Orchestrator merge / score / tier / qualify / filter."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services.discovery.orchestrator import run_discovery


def _make_taxonomies() -> MagicMock:
    tax = MagicMock()
    tax.niche_industry_affinity = {"groups": [{"niche_id": "beauty", "primary": ["cosmetics"]}]}
    tax.industry_audience_affinity = {"groups": []}
    tax.get_competitors.return_value = []
    tax.is_sensitive_industry.return_value = False
    return tax


def _brand_map(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"brands": list(entries)}


@pytest.mark.asyncio
async def test_unit__orchestrator__merges_sources_by_brand_id() -> None:
    """A brand hit by two searches gets one row with summed score + both source records."""
    tax = _make_taxonomies()

    # Add a competitor relationship so Search 3 also fires for MAC.
    def _competitors(name: str) -> list[str]:
        return ["MAC"] if name == "Sephora" else []

    tax.get_competitors.side_effect = _competitors
    bim = _brand_map(
        {
            "name": "MAC",
            "industry_id": "cosmetics",
            "creator_program_presence": ["direct"],
            "typical_campaign_tier": "macro",
            "company_stage": "public",
        }
    )
    talent_data = {
        "content_niches": ["beauty"],
        "previous_brands": [{"brand": "Sephora", "industry_id": "specialty-retail"}],
    }
    result = await run_discovery(
        talent_id="t1",
        talent_data=talent_data,
        brand_deals=[],
        taxonomies=tax,
        brand_industry_map=bim,
        # Restrict to deterministic searches — M7.4 wires _industry_extras into
        # the Exa seed for S15/S18 which would hit live APIs otherwise.
        enabled_searches=("search_3_competitors", "search_5_primary_industry"),
    )
    macs = [c for c in result.candidates if c.brand_id == "mac"]
    assert len(macs) == 1
    # Search 5 (primary, 0.30) + Search 3 (competitor, 0.25) = 0.55
    assert macs[0].score == pytest.approx(0.55, abs=0.01)
    tags = {s.search_tag for s in macs[0].sources}
    assert "primary_industry" in tags
    assert "competitor_of_previous" in tags


@pytest.mark.asyncio
async def test_unit__orchestrator__reengage_tag_overrides_tier() -> None:
    """A candidate hit by Search 1 (re-engage) gets tier=re-engage regardless of total score."""
    tax = _make_taxonomies()
    bim = _brand_map(
        {
            "name": "Gymshark",
            "industry_id": "activewear",
            "creator_program_presence": ["direct"],
            "typical_campaign_tier": "macro",
        }
    )
    today = date(2026, 1, 1)
    brand_deals = [
        {
            "brand_id": "gymshark",
            "brand_name": "Gymshark",
            "industry_id": "activewear",
            "ended_at": (today - timedelta(days=400)).isoformat(),
        }
    ]
    result = await run_discovery(
        talent_id="t1",
        talent_data={"content_niches": []},  # no niche overlap
        brand_deals=brand_deals,
        taxonomies=tax,
        brand_industry_map=bim,
        today=today,
        # Restrict to deterministic searches — M7.4 wires brand_deals
        # industries into the Exa seed via the bidirectional walk.
        enabled_searches=("search_1_reengagement", "search_5_primary_industry"),
    )
    gym = next((c for c in result.candidates if c.brand_id == "gymshark"), None)
    assert gym is not None
    assert gym.tier == "re-engage"


@pytest.mark.asyncio
async def test_unit__orchestrator__low_score_candidate_still_surfaces() -> None:
    """M7.4 — score is informational; no threshold drop. A tertiary-tier
    candidate at 0.06 still lands in result.candidates (the agent
    decides what to do with low-confidence hits)."""
    tax = _make_taxonomies()
    tax.niche_industry_affinity = {"groups": [{"niche_id": "beauty", "tertiary": ["telehealth"]}]}
    bim = _brand_map(
        {
            "name": "Hims",
            "industry_id": "telehealth",
            "creator_program_presence": ["direct"],
            "typical_campaign_tier": "macro",
        }
    )
    result = await run_discovery(
        talent_id="t1",
        talent_data={"content_niches": ["beauty"]},
        brand_deals=[],
        enabled_searches=("search_7_tertiary_industry",),
        taxonomies=tax,
        brand_industry_map=bim,
    )
    # Pre-M7.4 this was dropped at score < 0.10. Now it surfaces with the
    # score visible on the row.
    hims = next((c for c in result.candidates if c.brand_id == "hims"), None)
    assert hims is not None
    assert hims.score == pytest.approx(0.06)


@pytest.mark.asyncio
async def test_unit__orchestrator__blocked_industry_partitioned() -> None:
    """A blocked-industry candidate lands in result.blocked, not result.candidates."""
    tax = _make_taxonomies()
    bim = _brand_map(
        {
            "name": "MAC",
            "industry_id": "cosmetics",
            "creator_program_presence": ["direct"],
            "typical_campaign_tier": "macro",
            "company_stage": "public",
        }
    )
    # Restrict to deterministic searches — the Exa-driven 15/18 hit live
    # APIs and would surface many other cosmetics brands, breaking the
    # `len(result.blocked) == 1` invariant.
    result = await run_discovery(
        talent_id="t1",
        talent_data={
            "content_niches": ["beauty"],
            "brand_preferences": {"blocked_industries": ["cosmetics"]},
        },
        brand_deals=[],
        taxonomies=tax,
        brand_industry_map=bim,
        enabled_searches=("search_5_primary_industry",),
    )
    assert result.candidates == []
    assert len(result.blocked) == 1
    assert result.blocked[0].brand_id == "mac"


@pytest.mark.asyncio
async def test_unit__orchestrator__error_in_one_search_does_not_kill_run() -> None:
    """One search raising should NOT prevent the others from completing."""
    tax = _make_taxonomies()
    tax.niche_industry_affinity = {"groups": [{"niche_id": "beauty", "primary": ["cosmetics"]}]}
    # Force Search 9 to raise — invalid IAB segments structure.
    tax.industry_audience_affinity = {"groups": "not-a-list"}
    bim = _brand_map(
        {
            "name": "MAC",
            "industry_id": "cosmetics",
            "creator_program_presence": ["direct"],
            "typical_campaign_tier": "macro",
            "company_stage": "public",
        }
    )
    result = await run_discovery(
        talent_id="t1",
        talent_data={"content_niches": ["beauty"], "audience_demographics": {"interests": [677]}},
        brand_deals=[],
        taxonomies=tax,
        brand_industry_map=bim,
        # Restrict to deterministic searches — keep S5 firing + S9 erroring,
        # skip Exa-driven S15/S18 which would hit live APIs.
        enabled_searches=("search_5_primary_industry", "search_9_demographic_bridge"),
    )
    # Search 5 still produces MAC; Search 9 errored.
    assert any(c.brand_id == "mac" for c in result.candidates)
