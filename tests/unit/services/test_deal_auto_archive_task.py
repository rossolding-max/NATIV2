"""``process_ready_archives`` — transition gate-passing deals to archived."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.deal_auto_archive_task import process_ready_archives


def _close_stage_deal(deal_id: str) -> MagicMock:
    """A deal sitting at ``post_campaign_reporting`` whose gates are met.

    ``find_ready_for_archive`` already filters on gates + substage; this
    factory just gives the orchestrator something to transition.
    """
    d = MagicMock()
    d.deal_id = deal_id
    d.stage = "close"
    d.substage = "post_campaign_reporting"
    d.is_terminal = False
    d.is_won = False
    d.data = {
        "close": {
            "all_invoices_paid_at": "2026-05-01T00:00:00+00:00",
            "final_kpis": {"reach": 1000},
            "final_performance_report_attachment_id": "att_xyz",
        }
    }
    return d


@pytest.mark.asyncio
async def test_unit__auto_archive__transitions_ready_deals_to_archived() -> None:
    deals = [_close_stage_deal("d1"), _close_stage_deal("d2")]
    repo = MagicMock()
    repo.find_ready_for_archive = AsyncMock(return_value=deals)

    result = await process_ready_archives(repo)

    assert result == {"status": "ok", "archived": 2, "errors": []}
    for d in deals:
        assert d.substage == "archived"
        assert d.stage == "archived"
        assert d.is_terminal is True
        assert d.is_won is True
        # Audit trail captured.
        history = d.data["stage_history"]
        assert history[-1]["substage"] == "archived"
        assert history[-1]["by_agent_id"] == "system_auto_archive"


@pytest.mark.asyncio
async def test_unit__auto_archive__no_ready_deals_returns_zero_archived() -> None:
    repo = MagicMock()
    repo.find_ready_for_archive = AsyncMock(return_value=[])

    result = await process_ready_archives(repo)

    assert result == {"status": "ok", "archived": 0, "errors": []}


@pytest.mark.asyncio
async def test_unit__auto_archive__honours_limit_param() -> None:
    repo = MagicMock()
    repo.find_ready_for_archive = AsyncMock(return_value=[])

    await process_ready_archives(repo, limit=5)

    repo.find_ready_for_archive.assert_awaited_once_with(limit=5)


@pytest.mark.asyncio
async def test_unit__auto_archive__transition_error_isolates_per_deal() -> None:
    """If the orchestrator rejects one deal (e.g. wrong substage), others still archive."""
    good = _close_stage_deal("good")
    bad = _close_stage_deal("bad")
    # Force the orchestrator to fail on ``bad`` by giving it a substage
    # that cannot transition to archived.
    bad.substage = "new_lead"
    repo = MagicMock()
    repo.find_ready_for_archive = AsyncMock(return_value=[bad, good])

    result = await process_ready_archives(repo)

    assert result["archived"] == 1
    assert len(result["errors"]) == 1
    assert "deal=bad" in result["errors"][0]
    assert good.substage == "archived"
    assert bad.substage == "new_lead"
