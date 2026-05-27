"""Celery task: poll Smartlead for mailbox warmup status.

Runs on the ``default`` queue. Reads the agency_profile singleton, finds
the configured ``smartlead_mailbox_id``, queries Smartlead, and persists
the lifecycle field plus deliverability deltas into
``agency_profile.data.sending_mailboxes[0]``.

When warmup completes AND the rest of ``data`` passes schema validation,
the status auto-flips from ``warming_up`` → ``active``. If validation
fails (e.g. invalid invoice template added during the warmup window) the
task logs and leaves status at ``warming_up`` — manual /activate required.

The Beat schedule entry uses ``settings.cron_phase_4_8_detection_other_seconds``
(default 3600 = hourly) as the cadence. M5+ may introduce a dedicated
warmup cron if the hourly polling proves too aggressive or too slow.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from asgiref.sync import async_to_sync

from app.celery_app import app as celery_app
from app.db.session import async_session_factory
from app.errors import BusinessRuleError, ValidationError
from app.repositories.agency_profile import AgencyProfileRepository
from app.services.agency_setup import (
    AgencySetupService,
    check_ready_for_activation,
    validate_data_against_schema,
    validate_status_transition,
)
from app.utils.logging import get_logger
from app.vendors.smartlead import SmartleadClient

log = get_logger(__name__)


async def _poll_once() -> dict[str, Any]:
    """Run a single warmup poll. Returns a result dict for diagnostics + tests."""
    async with async_session_factory() as session:
        repo = AgencyProfileRepository(session)
        row = await repo.get_singleton()
        if row is None:
            log.info("warmup_poll_skipped", reason="no_agency_profile")
            return {"skipped": True, "reason": "no_agency_profile"}

        data = dict(row.data or {})
        mailboxes = list(data.get("sending_mailboxes") or [])
        if not mailboxes:
            log.info("warmup_poll_skipped", reason="no_mailbox")
            return {"skipped": True, "reason": "no_mailbox"}
        mbox = dict(mailboxes[0])
        sl_id = mbox.get("smartlead_mailbox_id")
        if not sl_id:
            log.info("warmup_poll_skipped", reason="no_smartlead_mailbox_id")
            return {"skipped": True, "reason": "no_smartlead_mailbox_id"}

        if mbox.get("warmup_status") == "complete":
            log.debug("warmup_poll_noop", reason="already_complete")
            return {"skipped": True, "reason": "already_complete"}

        client = SmartleadClient()
        sl_account = await client.get_email_account(sl_id)

        # Smartlead returns the warmup state nested under "warmup_details" on
        # the email-account endpoint. Map their lifecycle into our enum.
        sl_status = (
            (sl_account.get("warmup_details") or {}).get("status")
            or sl_account.get("warmup_status")
            or "in_progress"
        )
        translated = _translate_smartlead_warmup_status(str(sl_status))

        previous = mbox.get("warmup_status")
        mbox["warmup_status"] = translated
        # ``warmup_last_polled_at`` is NOT in the JSON Schema's
        # ``sendingMailbox`` shape (additionalProperties: false). If we
        # need that diagnostic later, add it to the schema first.
        if translated == "complete" and previous != "complete":
            mbox["completed_warmup_at"] = datetime.now(UTC).isoformat()

        mailboxes[0] = mbox
        service = AgencySetupService(repo)
        await service.apply_data_patch(row.agency_id, {"sending_mailboxes": mailboxes})

        result: dict[str, Any] = {
            "skipped": False,
            "previous_status": previous,
            "current_status": translated,
            "smartlead_mailbox_id": sl_id,
        }

        # Auto-flip to active when warmup just completed AND profile is ready.
        if translated == "complete" and previous != "complete":
            refreshed = await repo.get_singleton()
            try:
                validate_data_against_schema(dict(refreshed.data) if refreshed else {})
                check_ready_for_activation(dict(refreshed.data) if refreshed else {})
                validate_status_transition(refreshed.status if refreshed else "", "active")
            except (BusinessRuleError, ValidationError) as exc:
                log.warning(
                    "warmup_complete_but_profile_invalid",
                    error=str(exc),
                    detail=getattr(exc, "detail", None),
                )
                result["auto_activate_skipped"] = True
            else:
                if refreshed is not None:
                    await repo.set_status(refreshed.agency_id, "active")
                    result["status"] = "active"
                    log.info("warmup_complete_auto_activated", agency_id=str(refreshed.agency_id))

        await session.commit()
        return result


def _translate_smartlead_warmup_status(sl_status: str) -> str:
    """Map Smartlead's warmup terminology onto our internal enum.

    Smartlead uses 'paused' / 'in_progress' / 'completed' (sometimes
    'active' for ready-to-send). Our enum is
    ``pending | in_progress | complete | paused``.
    """
    s = sl_status.strip().lower()
    if s in {"completed", "complete", "active"}:
        return "complete"
    if s in {"paused", "stopped"}:
        return "paused"
    if s in {"pending", "not_started"}:
        return "pending"
    return "in_progress"


@celery_app.task(name="app.services.agency_warmup.poll_mailbox_warmup_status")
def poll_mailbox_warmup_status() -> dict[str, Any]:
    """Celery task entry point — runs the async poll via async_to_sync."""
    return async_to_sync(_poll_once)()
