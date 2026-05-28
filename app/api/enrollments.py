"""Phase 3b — Pitch Enrollments REST endpoints.

Implements the M9 surface per ``docs/outreach_workflow.md``:

- ``GET    /api/v1/talents/{talent_id}/enrollments``           (optional ``?state=``)
- ``GET    /api/v1/brands/{brand_id}/enrollments``
- ``GET    /api/v1/enrollments/{enrollment_id}``               — full step content
- ``PATCH  /api/v1/enrollments/{enrollment_id}``               — workflow patch
- ``POST   /api/v1/enrollments/{enrollment_id}/approve``       — Step-1 manual approval gate
- ``POST   /api/v1/talents/{talent_id}/outreach-generation/run`` — Celery enqueue
- ``POST   /api/v1/enrollments/{enrollment_id}/kill``          — kill + cross-roster cleanup

Step 1 approval triggers ``smartlead_push`` inline (the manual gate
doesn't need Celery — agents click once and want immediate feedback).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import APIResponse, make_meta
from app.db.session import get_db
from app.errors import NotFoundError, ValidationError
from app.repositories.brand import BrandRepository
from app.repositories.brand_contact import BrandContactRepository
from app.repositories.pitch_enrollment import PitchEnrollmentRepository
from app.repositories.talent import TalentRepository
from app.utils.logging import get_logger

log = get_logger(__name__)


brand_scoped_router = APIRouter(prefix="/brands", tags=["enrollments"])
talent_scoped_router = APIRouter(prefix="/talents", tags=["enrollments"])
top_level_router = APIRouter(prefix="/enrollments", tags=["enrollments"])


_STATE_PATTERN = r"^(awaiting_approval|active|paused|completed|killed)$"


class EnrollmentPatch(BaseModel):
    """Agent-driven workflow update."""

    model_config = ConfigDict(extra="allow")

    user_notes: str | None = None
    state: str | None = Field(default=None, pattern=_STATE_PATTERN)


class GenerateOutreachBody(BaseModel):
    """Body for ``POST /talents/{id}/outreach-generation/run``."""

    contact_id: str
    brand_id: str
    template_id: str | None = None


class KillBody(BaseModel):
    reason: str = Field(default="user_killed", max_length=120)


def _envelope(data: Any) -> APIResponse[Any]:
    return APIResponse[Any](data=data, meta=make_meta(), errors=[])


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "enrollment_id": row.enrollment_id,
        "talent_id": row.talent_id,
        "brand_id": row.brand_id,
        "contact_id": row.contact_id,
        "template_id": row.template_id,
        "state": row.state,
        "created_deal_id": row.created_deal_id,
        "killed_at": row.killed_at.isoformat() if row.killed_at else None,
        "data": row.data,
    }


def _agency_id_from_request(request: Request) -> UUID | None:
    value = getattr(request.app.state, "agency_id", None)
    if isinstance(value, UUID):
        return value
    return None


def _warn_missing_idempotency(request: Request) -> None:
    if not request.headers.get("Idempotency-Key"):
        log.warning(
            "idempotency_key_missing_on_write",
            method=request.method,
            path=request.url.path,
        )


# ── Talent-scoped endpoints ─────────────────────────────────────────


@talent_scoped_router.get("/{talent_id}/enrollments")
async def list_enrollments_by_talent(
    request: Request,
    talent_id: str,
    state: str | None = Query(default=None, pattern=_STATE_PATTERN),
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = PitchEnrollmentRepository(session, agency_id=agency_id)
    rows = await repo.find_by_talent(talent_id, state=state)
    return _envelope([_row_to_dict(r) for r in rows])


@talent_scoped_router.post(
    "/{talent_id}/outreach-generation/run",
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def trigger_outreach_generation(
    request: Request,
    talent_id: str,
    payload: GenerateOutreachBody,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Manual generation trigger — enqueues the Celery task."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    if await repo.get_by_talent_id(talent_id) is None:
        raise NotFoundError(f"talent {talent_id!r} not found", detail={"talent_id": talent_id})

    effective_agency = agency_id or UUID(int=0)
    from app.celery_app import app as celery_app

    enqueued = False
    try:
        celery_app.send_task(
            "app.services.outreach_generation_task.kick_off_outreach_generation",
            args=[
                talent_id,
                payload.contact_id,
                payload.brand_id,
                str(effective_agency),
                payload.template_id,
            ],
        )
        enqueued = True
    except Exception as exc:
        log.warning("outreach_generation_enqueue_failed", talent_id=talent_id, error=str(exc))

    return _envelope(
        {
            "talent_id": talent_id,
            "contact_id": payload.contact_id,
            "brand_id": payload.brand_id,
            "template_id": payload.template_id,
            "enqueued": enqueued,
            "task": "app.services.outreach_generation_task.kick_off_outreach_generation",
        }
    )


# ── Brand-scoped endpoints ──────────────────────────────────────────


@brand_scoped_router.get("/{brand_id}/enrollments")
async def list_enrollments_by_brand(
    request: Request,
    brand_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = PitchEnrollmentRepository(session, agency_id=agency_id)
    rows = await repo.find_by_brand(brand_id)
    return _envelope([_row_to_dict(r) for r in rows])


# ── Top-level enrollment endpoints ──────────────────────────────────


@top_level_router.get("/{enrollment_id}")
async def get_enrollment(
    request: Request,
    enrollment_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = PitchEnrollmentRepository(session, agency_id=agency_id)
    row = await repo.get_by_id(enrollment_id)
    if row is None:
        raise NotFoundError(
            f"pitch_enrollment {enrollment_id!r} not found",
            detail={"enrollment_id": enrollment_id},
        )
    return _envelope(_row_to_dict(row))


@top_level_router.patch("/{enrollment_id}")
async def patch_enrollment(
    payload: EnrollmentPatch,
    request: Request,
    enrollment_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = PitchEnrollmentRepository(session, agency_id=agency_id)
    diff = payload.model_dump(exclude_none=True, exclude_unset=True)
    row = await repo.patch_workflow_state(enrollment_id, diff)
    await session.commit()
    return _envelope(_row_to_dict(row))


@top_level_router.post("/{enrollment_id}/approve", status_code=http_status.HTTP_200_OK)
async def approve_enrollment(
    request: Request,
    enrollment_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step-1 approval gate — transitions ``awaiting_approval`` → ``active``
    and pushes the campaign to Smartlead inline.
    """
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = PitchEnrollmentRepository(session, agency_id=agency_id)
    enrollment = await repo.get_by_id(enrollment_id)
    if enrollment is None:
        raise NotFoundError(
            f"pitch_enrollment {enrollment_id!r} not found",
            detail={"enrollment_id": enrollment_id},
        )
    if enrollment.state != "awaiting_approval":
        raise ValidationError(
            f"enrollment must be in awaiting_approval; got state={enrollment.state!r}",
            detail={"state": enrollment.state},
        )

    # Resolve referenced contact + brand for the Smartlead push payload.
    contact_repo = BrandContactRepository(session, agency_id=agency_id)
    brand_repo = BrandRepository(session, agency_id=agency_id or UUID(int=0))
    contact = await contact_repo.get_by_id(enrollment.contact_id)
    brand = await brand_repo.get_by_id(enrollment.brand_id)
    if contact is None or brand is None:
        raise ValidationError(
            "missing contact or brand for enrollment",
            detail={
                "contact_found": contact is not None,
                "brand_found": brand is not None,
            },
        )

    from app.services.outreach.smartlead_push import push_to_smartlead
    from app.vendors.smartlead import SmartleadClient

    contact_dict = {
        "name": contact.name,
        "email_address": contact.email,
        "decision_role": contact.decision_role,
    }
    brand_dict = {"name": brand.name}
    steps = (enrollment.data or {}).get("steps") or []
    try:
        smartlead_meta = await push_to_smartlead(
            enrollment_id=enrollment_id,
            talent_id=enrollment.talent_id,
            template_id=enrollment.template_id,
            contact=contact_dict,
            brand=brand_dict,
            steps=steps,
            smartlead_client=SmartleadClient(),
        )
    except Exception as exc:
        log.warning(
            "enrollment_approve_smartlead_push_failed",
            enrollment_id=enrollment_id,
            error=str(exc),
        )
        raise ValidationError(
            f"smartlead push failed: {exc!s}",
            detail={"error": str(exc)},
        ) from exc

    now = datetime.now(UTC)
    row = await repo.patch_workflow_state(
        enrollment_id,
        {
            "state": "active",
            "approved_at": now.isoformat(),
            "smartlead_meta": smartlead_meta,
        },
    )
    await session.commit()
    return _envelope(_row_to_dict(row))


@top_level_router.post("/{enrollment_id}/kill", status_code=http_status.HTTP_200_OK)
async def kill_enrollment(
    payload: KillBody,
    request: Request,
    enrollment_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = PitchEnrollmentRepository(session, agency_id=agency_id)
    row = await repo.set_killed(enrollment_id, kill_reason=payload.reason)
    await session.commit()
    return _envelope(_row_to_dict(row))
