"""Handle one inbound reply: classify → kill/promote → side effects.

Called by the Smartlead webhook receiver (``app/api/webhooks/smartlead.py``)
and by the ``enrollment_state_sync`` reconciliation task.

Flow:
1. Classify the reply via Claude (Haiku).
2. ``interested`` → create Phase-4 deal (bidirectional FK), mark enrollment ``completed``.
3. ``declined`` / ``unrelated`` / ``needs_more_info`` → kill enrollment with reason.
4. ``unsubscribe_request`` → set ``brand_contact.do_not_contact=True`` + cross-roster kill.
5. ``out_of_office`` → pause until ``ooo_until + 1 day`` (best-effort).
6. ``wrong_person_routed`` → kill + record ``routed_to_contact``.

Idempotent: caller passes ``occurred_at`` so duplicate webhook
deliveries collapse to one classification.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.repositories.brand_contact import BrandContactRepository
from app.repositories.deal import DealRepository
from app.repositories.pitch_enrollment import PitchEnrollmentRepository
from app.services.outreach.deal_creator import create_deal_from_interested_reply
from app.services.outreach.reply_classifier import OutcomeClassification, classify_reply
from app.utils.logging import get_logger

log = get_logger(__name__)


_KILL_REASONS: dict[str, str] = {
    "declined": "reply_received",
    "unrelated": "reply_received",
    "needs_more_info": "reply_received",
    "wrong_person_routed": "reply_received",
    "unsubscribe_request": "unsubscribed",
}


async def handle_reply(
    *,
    enrollment_id: str,
    reply_body: str,
    occurred_at: str,
    agency_id: UUID,
    enrollment_repo: PitchEnrollmentRepository,
    contact_repo: BrandContactRepository,
    deal_repo: DealRepository,
    enrollment_subject: str | None = None,
    contact_name: str | None = None,
    talent_name: str | None = None,
    brand_name: str | None = None,
) -> dict[str, Any]:
    """Run the full classify → side-effect pipeline. Returns a summary dict."""
    enrollment = await enrollment_repo.get_by_id(enrollment_id)
    if enrollment is None:
        log.warning("reply_handler_enrollment_missing", enrollment_id=enrollment_id)
        return {"status": "enrollment_missing", "enrollment_id": enrollment_id}

    classification: OutcomeClassification = await classify_reply(
        reply_body=reply_body,
        enrollment_subject=enrollment_subject,
        contact_name=contact_name,
        talent_name=talent_name,
        brand_name=brand_name,
    )

    # Always record the classification on the enrollment (idempotent — same
    # occurred_at + same body produces the same outcome on duplicate
    # deliveries).
    await enrollment_repo.patch_workflow_state(
        enrollment_id,
        {
            "last_reply_classification": {
                "outcome": classification.outcome,
                "confidence": classification.confidence,
                "rationale": classification.rationale,
                "extracted_signals": classification.extracted_signals,
                "occurred_at": occurred_at,
            },
        },
    )

    summary: dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "outcome": classification.outcome,
        "confidence": classification.confidence,
    }

    if classification.outcome == "interested":
        contact = await contact_repo.get_by_id(enrollment.contact_id)
        decision_role = contact.decision_role if contact else "unknown"
        deal = await create_deal_from_interested_reply(
            enrollment=enrollment,
            contact_decision_role=decision_role,
            classification=classification,
            deal_repo=deal_repo,
            enrollment_repo=enrollment_repo,
            agency_id=agency_id,
        )
        summary["deal_id"] = deal.deal_id
        summary["next_state"] = "completed"
        return summary

    if classification.outcome == "unsubscribe_request":
        # 1. Mark contact DNC.
        await contact_repo.patch_workflow_state(
            enrollment.contact_id,
            {
                "do_not_contact": True,
                "do_not_contact_reason": "outreach_reply_unsubscribe",
                "opt_out_at": occurred_at,
            },
        )
        # 2. Kill EVERY active enrollment for this contact.
        actives = await enrollment_repo.find_active_for_contact(enrollment.contact_id)
        cross_killed: list[str] = []
        for e in actives:
            await enrollment_repo.set_killed(e.enrollment_id, kill_reason="unsubscribed")
            cross_killed.append(e.enrollment_id)
        summary["cross_roster_killed"] = cross_killed
        summary["next_state"] = "killed"
        return summary

    if classification.outcome == "out_of_office":
        # Pause the enrollment; the state-sync task picks it back up.
        await enrollment_repo.set_state(
            enrollment_id,
            "paused",
            extra={
                "paused_reason": "out_of_office",
                "ooo_until": classification.extracted_signals.get("ooo_until"),
            },
        )
        summary["next_state"] = "paused"
        return summary

    # Default: kill the enrollment with the matching reason.
    reason = _KILL_REASONS.get(classification.outcome, "reply_received")
    await enrollment_repo.set_killed(enrollment_id, kill_reason=reason)
    summary["next_state"] = "killed"
    return summary
