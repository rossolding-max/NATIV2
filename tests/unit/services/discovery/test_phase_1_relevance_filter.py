"""M7.7+ — LLM relevance filter tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.discovery._models import IndustryProposal
from app.services.discovery._phase_1_relevance_filter import (
    _PROTECTED_SOURCES,  # pyright: ignore[reportPrivateUsage]
    filter_irrelevant_proposals,
)


def _mock_llm_response(removals: list[dict[str, str]]) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps({"removals": removals})
    resp = MagicMock()
    resp.content = [block]
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=resp)
    return client


def _proposal(industry_id: str, source: str) -> IndustryProposal:
    return IndustryProposal(
        industry_id=industry_id,
        rationale=f"sample rationale for {industry_id}",
        source=source,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio
async def test_unit__filter__no_proposals_no_op() -> None:
    kept, removed = await filter_irrelevant_proposals([], {})
    assert kept == []
    assert removed == []


@pytest.mark.asyncio
async def test_unit__filter__only_protected_proposals_short_circuits() -> None:
    """When every proposal has a protected source, no LLM call fires."""
    proposals = [
        _proposal("toys", "affinity_primary"),
        _proposal("restaurants-qsr", "competitor_of_previous"),
    ]
    llm = MagicMock()
    llm.messages.create = AsyncMock(side_effect=AssertionError("should not be called"))
    kept, removed = await filter_irrelevant_proposals(
        proposals, {"content_niches": ["dad-life"]}, llm_client=llm
    )
    assert kept == proposals
    assert removed == []
    llm.messages.create.assert_not_called()


@pytest.mark.asyncio
async def test_unit__filter__removes_flagged_industry() -> None:
    proposals = [
        _proposal("toys", "affinity_primary"),  # protected
        _proposal("womenswear", "bidirectional_walk"),  # to be removed
        _proposal("luggage-travel-gear", "bidirectional_walk"),  # keep
    ]
    llm = _mock_llm_response([{"industry_id": "womenswear", "reason": "dad-life male creator"}])
    kept, removed = await filter_irrelevant_proposals(
        proposals,
        {"content_niches": ["dad-life"], "location": {"country": "US"}},
        llm_client=llm,
    )
    kept_ids = {p.industry_id for p in kept}
    assert "toys" in kept_ids  # protected stayed
    assert "luggage-travel-gear" in kept_ids  # not flagged
    assert "womenswear" not in kept_ids
    assert len(removed) == 1
    assert removed[0]["industry_id"] == "womenswear"
    assert removed[0]["original_source"] == "bidirectional_walk"
    assert removed[0]["reason"] == "dad-life male creator"


@pytest.mark.asyncio
async def test_unit__filter__protected_source_cannot_be_removed() -> None:
    """Even if the LLM flags a protected industry, the filter keeps it."""
    proposals = [
        _proposal("toys", "affinity_primary"),  # protected
        _proposal("womenswear", "bidirectional_walk"),
    ]
    # LLM tries to remove both, but toys is protected.
    llm = _mock_llm_response(
        [
            {"industry_id": "toys", "reason": "but actually no"},
            {"industry_id": "womenswear", "reason": "off-fit"},
        ]
    )
    kept, removed = await filter_irrelevant_proposals(
        proposals, {"content_niches": ["dad-life"]}, llm_client=llm
    )
    kept_ids = {p.industry_id for p in kept}
    assert "toys" in kept_ids  # protected ignores LLM's flag
    assert "womenswear" not in kept_ids
    # Only the non-protected removal lands.
    assert {r["industry_id"] for r in removed} == {"womenswear"}


@pytest.mark.asyncio
async def test_unit__filter__llm_failure_fails_open() -> None:
    """If the LLM call raises, return the original proposals untouched."""
    proposals = [_proposal("x", "bidirectional_walk")]
    llm = MagicMock()
    llm.messages.create = AsyncMock(side_effect=RuntimeError("anthropic down"))
    kept, removed = await filter_irrelevant_proposals(
        proposals, {"content_niches": []}, llm_client=llm
    )
    assert kept == proposals
    assert removed == []


@pytest.mark.asyncio
async def test_unit__filter__malformed_response_fails_open() -> None:
    """Non-JSON LLM output is treated as 'no removals'."""
    proposals = [_proposal("x", "bidirectional_walk")]
    block = MagicMock()
    block.type = "text"
    block.text = "i'm sorry, dave"
    resp = MagicMock()
    resp.content = [block]
    llm = MagicMock()
    llm.messages.create = AsyncMock(return_value=resp)
    kept, removed = await filter_irrelevant_proposals(
        proposals, {"content_niches": []}, llm_client=llm
    )
    assert kept == proposals
    assert removed == []


@pytest.mark.asyncio
async def test_unit__filter__duplicate_removal_only_counted_once() -> None:
    proposals = [_proposal("womenswear", "bidirectional_walk")]
    llm = _mock_llm_response(
        [
            {"industry_id": "womenswear", "reason": "a"},
            {"industry_id": "womenswear", "reason": "b"},  # dup
        ]
    )
    kept, removed = await filter_irrelevant_proposals(
        proposals, {"content_niches": ["dad-life"]}, llm_client=llm
    )
    assert kept == []
    assert len(removed) == 1


def test_unit__filter__protected_sources_set_includes_expected_sources() -> None:
    """Sanity check the protected source set covers the deliberate seeds."""
    assert "affinity_primary" in _PROTECTED_SOURCES
    assert "affinity_secondary" in _PROTECTED_SOURCES
    assert "affinity_tertiary" in _PROTECTED_SOURCES
    assert "competitor_of_previous" in _PROTECTED_SOURCES
    assert "similar_talent" in _PROTECTED_SOURCES
    # And the candidates for filtering should NOT be protected:
    assert "bidirectional_walk" not in _PROTECTED_SOURCES
    assert "adjacency" not in _PROTECTED_SOURCES
    assert "audience_demographic" not in _PROTECTED_SOURCES
    assert "life_stage" not in _PROTECTED_SOURCES
    assert "exclusivity_adjacent" not in _PROTECTED_SOURCES
