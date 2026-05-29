"""``process_ready_deals`` — enqueue prep-pack tasks + stamp debounce."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.deal_phase_4_5_auto_fire_task import process_ready_deals


def _ready_deal(deal_id: str) -> MagicMock:
    d = MagicMock()
    d.deal_id = deal_id
    d.agency_id = UUID(int=0)
    d.data = {}
    return d


@pytest.mark.asyncio
async def test_unit__auto_fire__enqueues_one_task_per_ready_deal() -> None:
    deals = [_ready_deal("deal_a"), _ready_deal("deal_b")]
    repo = MagicMock()
    repo.find_ready_for_prep_pack = AsyncMock(return_value=deals)
    send_task = MagicMock()
    when = datetime(2026, 5, 28, 16, 0, tzinfo=UTC)

    result = await process_ready_deals(repo, send_task=send_task, now=when)

    assert result == {"status": "ok", "enqueued": 2, "skipped_gated": 0, "errors": []}
    assert send_task.call_count == 2
    # Args shape: name + kwargs.
    for call, deal_id in zip(send_task.call_args_list, ["deal_a", "deal_b"], strict=True):
        assert call.args[0] == "app.tasks.pack_generation.generate_pack"
        kwargs = call.kwargs["kwargs"]
        assert kwargs["pack_type"] == "discovery_prep"
        assert kwargs["deal_id"] == deal_id
        assert kwargs["agent_id"] == "system"


@pytest.mark.asyncio
async def test_unit__auto_fire__stamps_prep_pack_enqueued_at_on_each_deal() -> None:
    deal = _ready_deal("deal_x")
    repo = MagicMock()
    repo.find_ready_for_prep_pack = AsyncMock(return_value=[deal])
    send_task = MagicMock()
    when = datetime(2026, 5, 28, 16, 0, tzinfo=UTC)

    await process_ready_deals(repo, send_task=send_task, now=when)

    assert deal.data["prep_pack_enqueued_at"] == when.isoformat()


@pytest.mark.asyncio
async def test_unit__auto_fire__preserves_existing_data_keys() -> None:
    deal = _ready_deal("deal_y")
    deal.data = {"user_notes": "existing", "next_action": {"summary": "ping"}}
    repo = MagicMock()
    repo.find_ready_for_prep_pack = AsyncMock(return_value=[deal])
    send_task = MagicMock()

    await process_ready_deals(repo, send_task=send_task, now=datetime.now(UTC))

    assert deal.data["user_notes"] == "existing"
    assert deal.data["next_action"]["summary"] == "ping"
    assert "prep_pack_enqueued_at" in deal.data


@pytest.mark.asyncio
async def test_unit__auto_fire__send_task_failure_is_isolated() -> None:
    """If send_task raises for one deal, the rest still process + error is recorded."""
    a, b, c = _ready_deal("a"), _ready_deal("b"), _ready_deal("c")
    repo = MagicMock()
    repo.find_ready_for_prep_pack = AsyncMock(return_value=[a, b, c])

    send_task = MagicMock(side_effect=[None, RuntimeError("broker down"), None])

    result = await process_ready_deals(repo, send_task=send_task, now=datetime.now(UTC))

    assert result["enqueued"] == 2
    assert len(result["errors"]) == 1
    assert "deal=b" in result["errors"][0]
    # ``b`` is NOT debounced — we want the next tick to retry it.
    assert "prep_pack_enqueued_at" in a.data
    assert "prep_pack_enqueued_at" not in b.data
    assert "prep_pack_enqueued_at" in c.data


@pytest.mark.asyncio
async def test_unit__auto_fire__no_ready_deals_returns_zero_enqueued() -> None:
    repo = MagicMock()
    repo.find_ready_for_prep_pack = AsyncMock(return_value=[])
    send_task = MagicMock()

    result = await process_ready_deals(repo, send_task=send_task, now=datetime.now(UTC))

    assert result == {"status": "ok", "enqueued": 0, "skipped_gated": 0, "errors": []}
    send_task.assert_not_called()


@pytest.mark.asyncio
async def test_unit__auto_fire__honours_per_tick_limit() -> None:
    """The helper passes through the ``limit`` to the repo."""
    repo = MagicMock()
    repo.find_ready_for_prep_pack = AsyncMock(return_value=[])
    send_task = MagicMock()

    await process_ready_deals(repo, send_task=send_task, now=datetime.now(UTC), limit=7)

    repo.find_ready_for_prep_pack.assert_awaited_once_with(limit=7)
