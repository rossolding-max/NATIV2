"""Reply handler pipeline — orchestrates classify + side effects."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.services import outreach_reply_handler
from app.services.outreach.reply_classifier import OutcomeClassification


def _enrollment() -> MagicMock:
    e = MagicMock()
    e.enrollment_id = "enr_42"
    e.contact_id = "bc_x"
    e.brand_id = "lululemon"
    e.talent_id = "t-1"
    return e


def _make_repos() -> dict[str, MagicMock]:
    enrollment_repo = MagicMock()
    enrollment_repo.get_by_id = AsyncMock(return_value=_enrollment())
    enrollment_repo.patch_workflow_state = AsyncMock()
    enrollment_repo.set_killed = AsyncMock()
    enrollment_repo.set_state = AsyncMock()
    enrollment_repo.find_active_for_contact = AsyncMock(return_value=[])

    contact = MagicMock()
    contact.decision_role = "buyer"
    contact_repo = MagicMock()
    contact_repo.get_by_id = AsyncMock(return_value=contact)
    contact_repo.patch_workflow_state = AsyncMock()

    deal = MagicMock()
    deal.deal_id = "deal_xyz"
    deal_repo = MagicMock()
    deal_repo.insert_lead_from_enrollment = AsyncMock(return_value=deal)
    return {
        "enrollment_repo": enrollment_repo,
        "contact_repo": contact_repo,
        "deal_repo": deal_repo,
    }


@pytest.mark.asyncio
async def test_unit__reply_handler__interested_creates_deal() -> None:
    repos = _make_repos()
    with patch.object(
        outreach_reply_handler,
        "classify_reply",
        AsyncMock(
            return_value=OutcomeClassification(
                outcome="interested",
                confidence=0.95,
                rationale="positive",
                extracted_signals={"asked_for_meeting": True},
            )
        ),
    ):
        out = await outreach_reply_handler.handle_reply(
            enrollment_id="enr_42",
            reply_body="sounds good",
            occurred_at="2026-05-28T16:00:00Z",
            agency_id=UUID(int=0),
            **repos,
        )
    assert out["outcome"] == "interested"
    assert out["deal_id"] == "deal_xyz"
    assert out["next_state"] == "completed"


@pytest.mark.asyncio
async def test_unit__reply_handler__unsubscribe_does_cross_roster_kill() -> None:
    repos = _make_repos()
    other = MagicMock()
    other.enrollment_id = "enr_other"
    repos["enrollment_repo"].find_active_for_contact = AsyncMock(return_value=[other])

    with patch.object(
        outreach_reply_handler,
        "classify_reply",
        AsyncMock(return_value=OutcomeClassification(outcome="unsubscribe_request")),
    ):
        out = await outreach_reply_handler.handle_reply(
            enrollment_id="enr_42",
            reply_body="remove me",
            occurred_at="2026-05-28T16:00:00Z",
            agency_id=UUID(int=0),
            **repos,
        )
    assert out["next_state"] == "killed"
    assert out["cross_roster_killed"] == ["enr_other"]
    repos["contact_repo"].patch_workflow_state.assert_awaited_once()
    diff = repos["contact_repo"].patch_workflow_state.await_args.args[1]
    assert diff["do_not_contact"] is True


@pytest.mark.asyncio
async def test_unit__reply_handler__out_of_office_pauses() -> None:
    repos = _make_repos()
    with patch.object(
        outreach_reply_handler,
        "classify_reply",
        AsyncMock(
            return_value=OutcomeClassification(
                outcome="out_of_office",
                extracted_signals={"ooo_until": "2026-06-15"},
            )
        ),
    ):
        out = await outreach_reply_handler.handle_reply(
            enrollment_id="enr_42",
            reply_body="OOO until June 15",
            occurred_at="2026-05-28T16:00:00Z",
            agency_id=UUID(int=0),
            **repos,
        )
    assert out["next_state"] == "paused"
    repos["enrollment_repo"].set_state.assert_awaited_once()


@pytest.mark.asyncio
async def test_unit__reply_handler__declined_kills() -> None:
    repos = _make_repos()
    with patch.object(
        outreach_reply_handler,
        "classify_reply",
        AsyncMock(return_value=OutcomeClassification(outcome="declined")),
    ):
        out = await outreach_reply_handler.handle_reply(
            enrollment_id="enr_42",
            reply_body="not interested",
            occurred_at="2026-05-28T16:00:00Z",
            agency_id=UUID(int=0),
            **repos,
        )
    assert out["next_state"] == "killed"
    repos["enrollment_repo"].set_killed.assert_awaited_once_with(
        "enr_42", kill_reason="reply_received"
    )


@pytest.mark.asyncio
async def test_unit__reply_handler__missing_enrollment_skips() -> None:
    repos = _make_repos()
    repos["enrollment_repo"].get_by_id = AsyncMock(return_value=None)
    out = await outreach_reply_handler.handle_reply(
        enrollment_id="enr_missing",
        reply_body="...",
        occurred_at="2026-05-28T16:00:00Z",
        agency_id=UUID(int=0),
        **repos,
    )
    assert out["status"] == "enrollment_missing"
