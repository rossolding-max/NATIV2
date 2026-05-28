"""Phase-3b → Phase-4 deal creation on ``interested`` reply.

The GAP-06 audit gate (project_plan.md M9): INSERT a Deal row AND
UPDATE the enrollment's ``created_deal_id`` in a single DB transaction
so a worker crash between the two leaves no orphan.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.models.sqla.deal import Deal
from app.repositories.deal import DealRepository
from app.repositories.pitch_enrollment import PitchEnrollmentRepository
from app.services.outreach.reply_classifier import OutcomeClassification
from app.utils.logging import get_logger

log = get_logger(__name__)


def _substage_from_signals(signals: dict[str, Any]) -> str:
    """If the contact asked for a meeting, jump straight to ``initial_call_scheduled``."""
    if signals.get("asked_for_meeting"):
        return "initial_call_scheduled"
    return "new_lead"


async def create_deal_from_interested_reply(
    *,
    enrollment: Any,  # PitchEnrollment row
    contact_decision_role: str,
    classification: OutcomeClassification,
    deal_repo: DealRepository,
    enrollment_repo: PitchEnrollmentRepository,
    agency_id: UUID,
) -> Deal:
    """INSERT deal + UPDATE enrollment.created_deal_id in one transaction.

    Both operations share the repos' session; no intermediate commit.
    The caller commits once after this returns.
    """
    if classification.outcome != "interested":
        raise ValueError(
            f"deal creation only fires on outcome=interested; got {classification.outcome!r}"
        )

    substage = _substage_from_signals(classification.extracted_signals)
    extra_data: dict[str, Any] = {
        "originating_classification": {
            "outcome": classification.outcome,
            "confidence": classification.confidence,
            "rationale": classification.rationale,
            "extracted_signals": classification.extracted_signals,
        },
    }
    deal = await deal_repo.insert_lead_from_enrollment(
        enrollment_id=enrollment.enrollment_id,
        talent_id=enrollment.talent_id,
        brand_id=enrollment.brand_id,
        contact_id=enrollment.contact_id,
        decision_role_at_pitch=contact_decision_role,
        substage=substage,
        extra_data=extra_data,
        agency_id=agency_id,
    )
    await enrollment_repo.patch_workflow_state(
        enrollment.enrollment_id,
        {"created_deal_id": deal.deal_id, "state": "completed"},
    )
    log.info(
        "outreach_deal_created",
        enrollment_id=enrollment.enrollment_id,
        deal_id=deal.deal_id,
        substage=substage,
    )
    return deal
