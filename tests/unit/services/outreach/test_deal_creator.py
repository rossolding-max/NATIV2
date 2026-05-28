"""Deal creator — GAP-06 bidirectional FK + decision_role snapshot."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.outreach import deal_creator
from app.services.outreach.reply_classifier import OutcomeClassification


def _enrollment(*, enrollment_id: str = "enr_42") -> MagicMock:
    e = MagicMock()
    e.enrollment_id = enrollment_id
    e.talent_id = "t-1"
    e.brand_id = "lululemon"
    e.contact_id = "bc_x"
    return e


@pytest.mark.asyncio
async def test_unit__deal_creator__interested_with_meeting_sets_initial_call_scheduled() -> None:
    deal = MagicMock()
    deal.deal_id = "deal_xyz"
    deal_repo = MagicMock()
    deal_repo.insert_lead_from_enrollment = AsyncMock(return_value=deal)
    enrollment_repo = MagicMock()
    enrollment_repo.patch_workflow_state = AsyncMock()

    out = await deal_creator.create_deal_from_interested_reply(
        enrollment=_enrollment(),
        contact_decision_role="buyer",
        classification=OutcomeClassification(
            outcome="interested",
            confidence=0.9,
            rationale="wants a call",
            extracted_signals={"asked_for_meeting": True},
        ),
        deal_repo=deal_repo,
        enrollment_repo=enrollment_repo,
        agency_id=UUID(int=0),
    )

    assert out is deal
    _args, kwargs = deal_repo.insert_lead_from_enrollment.call_args
    assert kwargs["substage"] == "initial_call_scheduled"
    assert kwargs["decision_role_at_pitch"] == "buyer"
    # Bidirectional FK update on the enrollment.
    enrollment_repo.patch_workflow_state.assert_awaited_once_with(
        "enr_42",
        {"created_deal_id": "deal_xyz", "state": "completed"},
    )


@pytest.mark.asyncio
async def test_unit__deal_creator__interested_without_meeting_uses_new_lead() -> None:
    deal_repo = MagicMock()
    deal_repo.insert_lead_from_enrollment = AsyncMock(return_value=MagicMock(deal_id="deal_x"))
    enrollment_repo = MagicMock()
    enrollment_repo.patch_workflow_state = AsyncMock()

    await deal_creator.create_deal_from_interested_reply(
        enrollment=_enrollment(),
        contact_decision_role="influencer",
        classification=OutcomeClassification(
            outcome="interested",
            confidence=0.7,
            extracted_signals={"asked_for_meeting": False},
        ),
        deal_repo=deal_repo,
        enrollment_repo=enrollment_repo,
        agency_id=UUID(int=0),
    )
    _args, kwargs = deal_repo.insert_lead_from_enrollment.call_args
    assert kwargs["substage"] == "new_lead"
    assert kwargs["decision_role_at_pitch"] == "influencer"


@pytest.mark.asyncio
async def test_unit__deal_creator__non_interested_rejected() -> None:
    deal_repo = MagicMock()
    enrollment_repo = MagicMock()
    with pytest.raises(ValueError, match="outcome=interested"):
        await deal_creator.create_deal_from_interested_reply(
            enrollment=_enrollment(),
            contact_decision_role="buyer",
            classification=OutcomeClassification(outcome="declined"),
            deal_repo=deal_repo,
            enrollment_repo=enrollment_repo,
            agency_id=UUID(int=0),
        )


@pytest.mark.asyncio
async def test_unit__deal_creator__originating_classification_recorded() -> None:
    deal_repo = MagicMock()
    deal_repo.insert_lead_from_enrollment = AsyncMock(return_value=MagicMock(deal_id="deal_x"))
    enrollment_repo = MagicMock()
    enrollment_repo.patch_workflow_state = AsyncMock()
    classification = OutcomeClassification(
        outcome="interested",
        confidence=0.85,
        rationale="positive reply asking for pricing",
        extracted_signals={"asked_for_pricing": True},
    )
    await deal_creator.create_deal_from_interested_reply(
        enrollment=_enrollment(),
        contact_decision_role="buyer",
        classification=classification,
        deal_repo=deal_repo,
        enrollment_repo=enrollment_repo,
        agency_id=UUID(int=0),
    )
    _args, kwargs = deal_repo.insert_lead_from_enrollment.call_args
    extra = kwargs["extra_data"]["originating_classification"]
    assert extra["outcome"] == "interested"
    assert extra["confidence"] == 0.85
    assert extra["extracted_signals"]["asked_for_pricing"] is True
