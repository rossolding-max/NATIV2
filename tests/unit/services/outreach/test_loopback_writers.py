"""Loopback writers — pitch_history append + last_re_engagement_pitch_date stamp."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.outreach import loopback_writers


@pytest.mark.asyncio
async def test_unit__loopback__append_pitch_history_writes_entry() -> None:
    existing = MagicMock()
    existing.data = {"pitch_history": []}
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=existing)
    repo.patch_workflow_state = AsyncMock(return_value=existing)

    await loopback_writers.append_pitch_history(
        contact_repo=repo,
        contact_id="bc_x",
        talent_id="t-1",
        enrollment_id="enr_42",
        template_id="buyer-direct-pitch",
    )
    repo.patch_workflow_state.assert_awaited_once()
    args, _ = repo.patch_workflow_state.call_args
    contact_id, diff = args
    assert contact_id == "bc_x"
    assert len(diff["pitch_history"]) == 1
    entry = diff["pitch_history"][0]
    assert entry["talent_id"] == "t-1"
    assert entry["enrollment_id"] == "enr_42"
    assert entry["outcome"] == "in_flight"


@pytest.mark.asyncio
async def test_unit__loopback__append_preserves_existing_history() -> None:
    existing = MagicMock()
    existing.data = {"pitch_history": [{"talent_id": "t-other", "enrollment_id": "enr_old"}]}
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=existing)
    repo.patch_workflow_state = AsyncMock(return_value=existing)

    await loopback_writers.append_pitch_history(
        contact_repo=repo,
        contact_id="bc_x",
        talent_id="t-1",
        enrollment_id="enr_42",
        template_id="buyer-direct-pitch",
    )
    args, _ = repo.patch_workflow_state.call_args
    _, diff = args
    assert len(diff["pitch_history"]) == 2
    assert diff["pitch_history"][0]["talent_id"] == "t-other"
    assert diff["pitch_history"][1]["talent_id"] == "t-1"


@pytest.mark.asyncio
async def test_unit__loopback__append_skips_missing_contact() -> None:
    repo = MagicMock()
    repo.get_by_id = AsyncMock(return_value=None)
    repo.patch_workflow_state = AsyncMock()
    await loopback_writers.append_pitch_history(
        contact_repo=repo,
        contact_id="bc_missing",
        talent_id="t-1",
        enrollment_id="enr_42",
        template_id="x",
    )
    repo.patch_workflow_state.assert_not_called()


@pytest.mark.asyncio
async def test_unit__loopback__set_re_engagement_pitch_date_updates_deal() -> None:
    deal = MagicMock()
    deal.brand_id = "gymshark"
    deal.data = {"campaign_date": "2024-06-01"}
    session = MagicMock()
    session.flush = AsyncMock()
    repo = MagicMock()
    repo.find_by_talent = AsyncMock(return_value=[deal])
    repo._session = session  # pyright: ignore[reportPrivateUsage]

    today = datetime.now(UTC).date()
    await loopback_writers.set_re_engagement_pitch_date(
        brand_deal_repo=repo,
        talent_id="t-1",
        brand_id="gymshark",
        fired_at=today,
    )
    assert deal.data["last_re_engagement_pitch_date"] == today.isoformat()
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_unit__loopback__set_re_engagement_no_historical_deal_failsoft() -> None:
    session = MagicMock()
    session.flush = AsyncMock()
    repo = MagicMock()
    repo.find_by_talent = AsyncMock(return_value=[])  # no historical deals
    repo._session = session  # pyright: ignore[reportPrivateUsage]

    await loopback_writers.set_re_engagement_pitch_date(
        brand_deal_repo=repo,
        talent_id="t-1",
        brand_id="missing",
    )
    session.flush.assert_not_called()
