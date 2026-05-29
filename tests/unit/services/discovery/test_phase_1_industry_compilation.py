"""M7.7 — Phase 1 industry-compilation composition tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.discovery._models import IndustryProposal
from app.services.discovery.phase_1_industry_compilation import (
    _dedup_with_alternates,  # pyright: ignore[reportPrivateUsage]
    compile_industry_universe,
)


def _mock_tax(
    *,
    niche_groups: list[dict[str, Any]] | None = None,
    industries: dict[str, dict[str, Any]] | None = None,
    niches: dict[str, dict[str, Any]] | None = None,
) -> MagicMock:
    tax = MagicMock()
    tax.niche_industry_affinity = {"groups": niche_groups or []}
    tax.industry_audience_affinity = {"groups": []}
    tax.industries = industries or {}
    tax.niches = niches or {}
    tax.get_industry.side_effect = lambda iid: (industries or {}).get(iid)  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]
    tax.get_niche.side_effect = lambda nid: (niches or {}).get(nid)  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]
    tax.get_industry_parent.side_effect = lambda iid: (  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]
        (industries or {}).get(iid, {}).get("parent")
    )
    tax.get_sub_industries.side_effect = lambda iid: sorted(  # pyright: ignore[reportUnknownLambdaType,reportUnknownArgumentType]
        c for c, n in (industries or {}).items() if n.get("parent") == iid
    )
    return tax


# ── _dedup_with_alternates ─────────────────────────────────────────


def test_unit__dedup__affinity_primary_wins_over_softener() -> None:
    """When affinity and softener both surface the same industry, affinity wins."""
    proposals = [
        IndustryProposal(industry_id="toys", rationale="r1", source="softener"),
        IndustryProposal(industry_id="toys", rationale="r2", source="affinity_primary"),
    ]
    pairs = _dedup_with_alternates(proposals)
    assert len(pairs) == 1
    winner, alternates = pairs[0]
    assert winner.source == "affinity_primary"
    assert alternates[0].source == "softener"


def test_unit__dedup__preserves_alternate_rationales() -> None:
    proposals = [
        IndustryProposal(industry_id="x", rationale="primary", source="affinity_primary"),
        IndustryProposal(industry_id="x", rationale="walked", source="bidirectional_walk"),
        IndustryProposal(industry_id="x", rationale="softener", source="softener"),
    ]
    pairs = _dedup_with_alternates(proposals)
    assert len(pairs) == 1
    winner, alternates = pairs[0]
    assert winner.source == "affinity_primary"
    assert {a.source for a in alternates} == {"bidirectional_walk", "softener"}


# ── compile_industry_universe (full) ───────────────────────────────


@pytest.mark.asyncio
async def test_unit__compile__kevin_shaped_surfaces_affinity_plus_walk() -> None:
    """Kevin: dad-life niche + 1 past brand in restaurants-qsr, no audience."""
    tax = _mock_tax(
        niche_groups=[
            {
                "niche_id": "dad-life",
                "primary": ["toys", "grocery"],
                "secondary": ["restaurants-qsr"],
            }
        ],
        industries={
            "toys": {"id": "toys", "parent": None},
            "grocery": {"id": "grocery", "parent": None},
            "restaurants-qsr": {"id": "restaurants-qsr", "parent": "restaurants"},
            "restaurants": {"id": "restaurants", "parent": None},
            "fast-fashion": {"id": "fast-fashion", "parent": "restaurants"},  # synthetic sibling
        },
        niches={"dad-life": {"id": "dad-life", "parent": None}},
    )
    talent_data = {
        "content_niches": ["dad-life"],
        "previous_brands": [{"brand": "Dunkin'", "industry_id": "restaurants-qsr"}],
        "audience_demographics": {},
        "brand_preferences": {},
    }
    # Mock the softener to return one extra industry.
    with patch(
        "app.services.discovery.phase_1_industry_compilation._industry_softener.run",
        new=AsyncMock(return_value=["streaming-services"]),
    ):
        pairs = await compile_industry_universe(
            talent_data=talent_data, brand_deals=[], taxonomies=tax
        )

    ids = {winner.industry_id for winner, _ in pairs}
    # affinity primary + secondary + past-brand + walked siblings + softener
    assert "toys" in ids
    assert "grocery" in ids
    assert "restaurants-qsr" in ids
    assert "streaming-services" in ids
    # restaurants (parent of restaurants-qsr) surfaces via bidirectional walk
    assert "restaurants" in ids
    # All winners have non-empty rationale.
    for winner, _ in pairs:
        assert winner.rationale.strip() != ""


@pytest.mark.asyncio
async def test_unit__compile__multi_source_dedup_keeps_highest_priority() -> None:
    """An industry surfaced by affinity AND past-brand walk → affinity wins."""
    tax = _mock_tax(
        niche_groups=[{"niche_id": "dad-life", "primary": ["restaurants-qsr"]}],
        industries={
            "restaurants-qsr": {"id": "restaurants-qsr", "parent": "restaurants"},
            "restaurants": {"id": "restaurants", "parent": None},
        },
        niches={"dad-life": {"id": "dad-life", "parent": None}},
    )
    talent_data = {
        "content_niches": ["dad-life"],
        "previous_brands": [{"brand": "Dunkin'", "industry_id": "restaurants-qsr"}],
        "audience_demographics": {},
        "brand_preferences": {},
    }
    with patch(
        "app.services.discovery.phase_1_industry_compilation._industry_softener.run",
        new=AsyncMock(return_value=[]),
    ):
        pairs = await compile_industry_universe(
            talent_data=talent_data, brand_deals=[], taxonomies=tax
        )
    qsr = next((w, a) for w, a in pairs if w.industry_id == "restaurants-qsr")
    winner, alternates = qsr
    assert winner.source == "affinity_primary"
    # Past-brand source is in alternates.
    assert any(a.source == "competitor_of_previous" for a in alternates)


@pytest.mark.asyncio
async def test_unit__compile__no_softener_when_disabled() -> None:
    """When softener returns [], the rest of Phase 1 still works."""
    tax = _mock_tax(
        niche_groups=[{"niche_id": "dad-life", "primary": ["toys"]}],
        industries={"toys": {"id": "toys", "parent": None}},
        niches={"dad-life": {"id": "dad-life", "parent": None}},
    )
    with patch(
        "app.services.discovery.phase_1_industry_compilation._industry_softener.run",
        new=AsyncMock(return_value=[]),
    ):
        pairs = await compile_industry_universe(
            talent_data={"content_niches": ["dad-life"], "previous_brands": []},
            brand_deals=[],
            taxonomies=tax,
        )
    ids = {w.industry_id for w, _ in pairs}
    assert ids == {"toys"}
