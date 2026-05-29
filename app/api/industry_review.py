"""M7.7 Phase 1.5 REST surface — industry-review queue.

Three endpoints:

  - GET    /talents/{id}/industry-review            -> fetch the pending review
  - PATCH  /talents/{id}/industry-review            -> add/remove industries
  - POST   /talents/{id}/industry-review/approve    -> approve + enqueue Phase 2

A pending review is created by the orchestrator when a ``full_build``
discovery run fires. The agency operator interacts with these endpoints
until approval, then Phase 2 takes over.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Request
from fastapi import status as http_status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import APIResponse, make_meta
from app.db.session import get_db
from app.errors import NotFoundError
from app.repositories.industry_review import IndustryReviewRepository
from app.repositories.talent import TalentRepository
from app.utils.logging import get_logger

log = get_logger(__name__)


talent_scoped_router = APIRouter(prefix="/talents", tags=["industry-review"])


# ── Request models ───────────────────────────────────────────────────


class IndustryReviewPatch(BaseModel):
    """Patch shape: add new entries + flip approval on existing entries."""

    added: list[dict[str, Any]] | None = None  # list[{industry_id, rationale?}]
    removed: list[str] | None = None  # list[industry_id]


# ── Helpers ──────────────────────────────────────────────────────────


def _envelope(data: Any) -> APIResponse[Any]:
    return APIResponse[Any](data=data, meta=make_meta(), errors=[])


def _agency_id_from_request(request: Request) -> UUID | None:
    value = getattr(request.app.state, "agency_id", None)
    if isinstance(value, UUID):
        return value
    return None


def _review_to_dict(row: Any) -> dict[str, Any]:
    return {
        "review_id": row.review_id,
        "talent_id": row.talent_id,
        "status": row.status,
        "items": row.items or [],
        "search_run_id": row.search_run_id,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


# ── Endpoints ────────────────────────────────────────────────────────


@talent_scoped_router.get("/{talent_id}/industry-review")
async def get_industry_review(
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Return the most-recent pending review for the talent.

    404 when no pending review exists (talent hasn't triggered full_build,
    or the previous review was already approved/rejected).
    """
    agency_id = _agency_id_from_request(request)
    talents = TalentRepository(session, agency_id=agency_id)
    talent_row = await talents.get_by_talent_id(talent_id)
    if talent_row is None:
        raise NotFoundError(f"talent {talent_id!r} not found", detail={"talent_id": talent_id})

    repo = IndustryReviewRepository(session, agency_id=agency_id)
    review = await repo.get_pending(talent_id)
    if review is None:
        raise NotFoundError(
            f"no pending industry-review for talent {talent_id!r}",
            detail={
                "talent_id": talent_id,
                "hint": "trigger /brand-discovery/run with mode=full_build first",
            },
        )
    return _envelope(_review_to_dict(review))


@talent_scoped_router.patch("/{talent_id}/industry-review")
async def patch_industry_review(
    request: Request,
    talent_id: str,
    payload: IndustryReviewPatch = Body(default_factory=IndustryReviewPatch),  # noqa: B008
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Add new industries + flip approval on existing ones.

    Only the pending review is patchable; approved/rejected records are
    immutable.
    """
    agency_id = _agency_id_from_request(request)
    repo = IndustryReviewRepository(session, agency_id=agency_id)
    review = await repo.get_pending(talent_id)
    if review is None:
        raise NotFoundError(
            f"no pending industry-review for talent {talent_id!r}",
            detail={"talent_id": talent_id},
        )

    updated = await repo.patch_items(
        review.review_id,
        added=payload.added,
        removed=payload.removed,
    )
    await session.commit()
    return _envelope(_review_to_dict(updated))


@talent_scoped_router.post(
    "/{talent_id}/industry-review/approve",
    status_code=http_status.HTTP_202_ACCEPTED,
)
async def approve_industry_review(
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Approve the pending review → enqueue Phase 2 brand-universe build."""
    agency_id = _agency_id_from_request(request)
    repo = IndustryReviewRepository(session, agency_id=agency_id)
    review = await repo.get_pending(talent_id)
    if review is None:
        raise NotFoundError(
            f"no pending industry-review for talent {talent_id!r}",
            detail={"talent_id": talent_id},
        )

    approved = await repo.mark_approved(review.review_id)
    await session.commit()

    # Enqueue Phase 2 Celery task. The task itself ships in Commit 5;
    # for now we emit the enqueue so the contract is in place.
    from app.celery_app import app as celery_app

    effective_agency = agency_id or UUID(int=0)
    enqueued = False
    try:
        celery_app.send_task(
            "app.services.talent_background_research.kick_off_phase_2_brand_universe",
            args=[talent_id, str(effective_agency), approved.review_id],
        )
        enqueued = True
    except Exception as exc:
        log.warning("phase_2_enqueue_failed", review_id=approved.review_id, error=str(exc))

    return _envelope(
        {
            "review_id": approved.review_id,
            "talent_id": talent_id,
            "status": "approved",
            "phase_2_enqueued": enqueued,
            "approved_industry_count": sum(
                1 for item in (approved.items or []) if item.get("approved")
            ),
        }
    )
