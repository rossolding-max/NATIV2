"""M11 — verify ``process_ready_deals`` honours the auto-fire gate."""

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
async def test_unit__gate__off_skips_send_task_but_stamps_debounce() -> None:
    deals = [_ready_deal("a"), _ready_deal("b")]
    repo = MagicMock()
    repo.find_ready_for_prep_pack = AsyncMock(return_value=deals)
    send_task = MagicMock()
    when = datetime(2026, 5, 29, 9, 0, tzinfo=UTC)

    result = await process_ready_deals(
        repo,
        send_task=send_task,
        now=when,
        auto_fire_enabled=False,
    )

    # send_task not called.
    send_task.assert_not_called()
    assert result["enqueued"] == 0
    assert result["skipped_gated"] == 2
    # But the debounce stamp landed on every ready deal.
    assert deals[0].data["prep_pack_enqueued_at"] == when.isoformat()
    assert deals[1].data["prep_pack_enqueued_at"] == when.isoformat()


@pytest.mark.asyncio
async def test_unit__gate__on_fires_send_task_and_stamps_debounce() -> None:
    deal = _ready_deal("x")
    repo = MagicMock()
    repo.find_ready_for_prep_pack = AsyncMock(return_value=[deal])
    send_task = MagicMock()
    when = datetime(2026, 5, 29, 9, 0, tzinfo=UTC)

    result = await process_ready_deals(
        repo,
        send_task=send_task,
        now=when,
        auto_fire_enabled=True,
    )

    send_task.assert_called_once()
    assert result["enqueued"] == 1
    assert result["skipped_gated"] == 0
    assert deal.data["prep_pack_enqueued_at"] == when.isoformat()


@pytest.mark.asyncio
async def test_unit__gate__default_is_enabled_for_backwards_compat() -> None:
    """Existing M10 tests don't set ``auto_fire_enabled``; default = True."""
    deal = _ready_deal("z")
    repo = MagicMock()
    repo.find_ready_for_prep_pack = AsyncMock(return_value=[deal])
    send_task = MagicMock()

    await process_ready_deals(repo, send_task=send_task, now=datetime.now(UTC))

    send_task.assert_called_once()
