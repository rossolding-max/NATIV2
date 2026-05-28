"""5-minute Celery beat task — reconcile enrollment state with Smartlead.

Walks every ``state="active"`` enrollment and asks Smartlead for the
current campaign status + engagement events. Catches webhook misses
(network failures, dedupe bugs). Cheap by design — only touches
enrollments that are actually live.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync

from app.celery_app import app as celery_app
from app.utils.logging import get_logger

log = get_logger(__name__)


async def _sync_async(agency_id: str | None = None) -> dict[str, Any]:
    """Walk active enrollments + reconcile with Smartlead."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.config import settings
    from app.db.session import engine
    from app.repositories.pitch_enrollment import PitchEnrollmentRepository
    from app.vendors.smartlead import SmartleadClient

    await engine.dispose()
    agency_uuid = UUID(agency_id) if agency_id else UUID(int=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    if settings.smartlead_api_key is None:
        log.info("enrollment_state_sync_skipped_no_api_key")
        return {"status": "skipped_no_smartlead_key"}

    smartlead = SmartleadClient()
    synced = 0
    errors: list[str] = []

    async with factory() as session:
        repo = PitchEnrollmentRepository(session, agency_id=agency_uuid)
        active = await repo.find_by_state("active")
        for enrollment in active:
            meta = (enrollment.data or {}).get("smartlead_meta") or {}
            campaign_id = meta.get("campaign_id")
            if not campaign_id:
                continue
            try:
                resp = await smartlead.get_campaign_status(str(campaign_id))
            except Exception as exc:
                errors.append(f"enrollment={enrollment.enrollment_id}: {exc!s}")
                continue
            # Mirror Smartlead's high-level status onto the enrollment.
            current = (resp or {}).get("status")
            if current == "COMPLETED":
                await repo.set_state(enrollment.enrollment_id, "completed")
                synced += 1
            elif current == "PAUSED":
                await repo.set_state(enrollment.enrollment_id, "paused")
                synced += 1
        await session.commit()

    log.info("enrollment_state_sync_complete", synced=synced, errors=len(errors))
    return {"status": "ok", "synced": synced, "errors": errors}


@celery_app.task(name="app.services.enrollment_state_sync.enrollment_state_sync")
def enrollment_state_sync(agency_id: str | None = None) -> dict[str, Any]:
    """Celery beat entry point — runs every 5 minutes."""
    return async_to_sync(_sync_async)(agency_id)
