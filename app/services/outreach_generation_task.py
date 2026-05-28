"""M9 — Celery task wrapping the outreach orchestrator.

Fires from ``POST /api/v1/talents/{id}/outreach-generation/run`` (and,
in M9.1, auto-fires from M8 contact enrichment when
``settings.outreach_auto_enroll == True``).

Per the worker-bootstrap memory: registers in ``app/celery_app.py``
``include=``, accepts ``agency_id`` arg, disposes the engine at the
start of the task body to escape ``async_to_sync``'s per-call event loop.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync

from app.celery_app import app as celery_app
from app.utils.logging import get_logger

log = get_logger(__name__)


async def _kick_off_async(
    talent_id: str,
    contact_id: str,
    brand_id: str,
    agency_id: str,
    template_id: str | None = None,
) -> dict[str, Any]:
    """Generate one enrollment for (talent, contact, brand) + persist + snapshot."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import engine
    from app.repositories.brand import BrandRepository
    from app.repositories.brand_contact import BrandContactRepository
    from app.repositories.pitch_angle import PitchAngleRepository
    from app.repositories.pitch_enrollment import PitchEnrollmentRepository
    from app.repositories.pitch_template import PitchTemplateRepository
    from app.repositories.talent import TalentRepository
    from app.services.outreach.orchestrator import generate_enrollment
    from app.services.outreach.snapshot import write_snapshot

    await engine.dispose()
    agency_uuid = UUID(agency_id)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        talents = TalentRepository(session, agency_id=agency_uuid)
        contacts = BrandContactRepository(session, agency_id=agency_uuid)
        brands = BrandRepository(session, agency_id=agency_uuid)
        templates = PitchTemplateRepository(session, agency_id=agency_uuid)
        angles = PitchAngleRepository(session, agency_id=agency_uuid)
        enrollments = PitchEnrollmentRepository(session, agency_id=agency_uuid)

        result = await generate_enrollment(
            talent_id=talent_id,
            contact_id=contact_id,
            brand_id=brand_id,
            agency_id=agency_uuid,
            template_id=template_id,
            talent_repo=talents,
            contact_repo=contacts,
            brand_repo=brands,
            template_repo=templates,
            angle_repo=angles,
            enrollment_repo=enrollments,
        )
        await session.commit()

    snapshot_path = write_snapshot(result) if result.draft else None
    log.info(
        "outreach_generation_complete",
        talent_id=talent_id,
        contact_id=contact_id,
        brand_id=brand_id,
        enrollment_id=result.draft.enrollment_id if result.draft else None,
        block_reason=result.block_reason,
        snapshot=str(snapshot_path) if snapshot_path else None,
    )
    return {
        "talent_id": talent_id,
        "contact_id": contact_id,
        "brand_id": brand_id,
        "enrollment_id": result.draft.enrollment_id if result.draft else None,
        "block_reason": result.block_reason,
        "warnings": result.warnings,
        "errors": result.errors,
    }


@celery_app.task(name="app.services.outreach_generation_task.kick_off_outreach_generation")
def kick_off_outreach_generation(
    talent_id: str,
    contact_id: str,
    brand_id: str,
    agency_id: str,
    template_id: str | None = None,
) -> dict[str, Any]:
    """Celery entry point — bridges async to sync via async_to_sync."""
    return async_to_sync(_kick_off_async)(talent_id, contact_id, brand_id, agency_id, template_id)
