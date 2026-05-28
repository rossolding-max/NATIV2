"""Phase 2 — Brand Candidates REST endpoints.

Implements the M7 surface per ``docs/brand_discovery.md``:

  - ``GET    /api/v1/talents/{talent_id}/brand-candidates``  -> list (optional ?tier=)
  - ``GET    /api/v1/brand-candidates/{candidate_id}``       -> fetch
  - ``PATCH  /api/v1/brand-candidates/{candidate_id}``       -> workflow patch
  - ``POST   /api/v1/talents/{talent_id}/brand-discovery/run`` -> manual rerun

The manual rerun enqueues the same Celery task that ``/activate`` fires
(``app.services.talent_background_research.kick_off_brand_discovery``).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import APIResponse, make_meta
from app.db.session import get_db
from app.errors import NotFoundError
from app.repositories.brand_candidate import BrandCandidateRepository
from app.repositories.talent import TalentRepository
from app.utils.logging import get_logger

log = get_logger(__name__)


# Two routers — talent-scoped list/rerun + top-level deal-id addressing.
talent_scoped_router = APIRouter(prefix="/talents", tags=["brand-candidates"])
top_level_router = APIRouter(prefix="/brand-candidates", tags=["brand-candidates"])


_TIER_PATTERN = r"^(re-engage|primary|secondary|tertiary)$"
_STATUS_PATTERN = r"^(new|shortlisted|pitched|responded|negotiating|closed_won|closed_lost|parked)$"


# ── Request models ───────────────────────────────────────────────────


class CandidatePatch(BaseModel):
    """Agent-driven workflow update — status / assigned_to / notes / pitch_history."""

    model_config = ConfigDict(extra="allow")

    status: str | None = Field(default=None, pattern=_STATUS_PATTERN)
    assigned_to: str | None = None
    user_notes: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _envelope(data: Any) -> APIResponse[Any]:
    return APIResponse[Any](data=data, meta=make_meta(), errors=[])


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "candidate_id": row.candidate_id,
        "talent_id": row.talent_id,
        "brand_id": row.brand_id,
        "tier": row.tier,
        "status": row.status,
        "score": float(row.score) if row.score is not None else None,
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


# ── Talent-scoped endpoints ──────────────────────────────────────────


@talent_scoped_router.get("/{talent_id}/brand-candidates")
async def list_brand_candidates(
    request: Request,
    talent_id: str,
    tier: str | None = Query(default=None, pattern=_TIER_PATTERN),
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """List candidates for a talent. Optional ``?tier=primary``."""
    agency_id = _agency_id_from_request(request)
    repo = BrandCandidateRepository(session, agency_id=agency_id)
    rows = (
        await repo.find_by_tier(talent_id, tier) if tier else await repo.find_by_talent(talent_id)
    )
    return _envelope([_row_to_dict(row) for row in rows])


@talent_scoped_router.post(
    "/{talent_id}/brand-discovery/run", status_code=http_status.HTTP_202_ACCEPTED
)
async def trigger_brand_discovery(
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Manually re-run discovery for this talent.

    Confirms the talent exists, then enqueues the same Celery task that
    M5's ``/activate`` fires. Returns 202 (Accepted) immediately — the
    task runs in the background.
    """
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    row = await repo.get_by_talent_id(talent_id)
    if row is None:
        raise NotFoundError(f"talent {talent_id!r} not found", detail={"talent_id": talent_id})

    from app.celery_app import app as celery_app

    enqueued = False
    try:
        celery_app.send_task(
            "app.services.talent_background_research.kick_off_brand_discovery",
            args=[talent_id],
        )
        enqueued = True
    except Exception as exc:
        log.warning("brand_discovery_enqueue_failed", talent_id=talent_id, error=str(exc))

    return _envelope(
        {
            "talent_id": talent_id,
            "enqueued": enqueued,
            "task": "app.services.talent_background_research.kick_off_brand_discovery",
        }
    )


# ── Top-level candidate endpoints ────────────────────────────────────


@top_level_router.get("/{candidate_id}")
async def get_brand_candidate(
    request: Request,
    candidate_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = BrandCandidateRepository(session, agency_id=agency_id)
    row = await repo.get_by_id(candidate_id)
    if row is None:
        raise NotFoundError(
            f"brand_candidate {candidate_id!r} not found", detail={"candidate_id": candidate_id}
        )
    return _envelope(_row_to_dict(row))


@top_level_router.patch("/{candidate_id}")
async def patch_brand_candidate(
    payload: CandidatePatch,
    request: Request,
    candidate_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Agent workflow patch: status, assigned_to, user_notes, pitch_history, etc."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = BrandCandidateRepository(session, agency_id=agency_id)
    diff = payload.model_dump(exclude_none=True)
    updated = await repo.patch_workflow_state(candidate_id, diff)
    await session.commit()
    return _envelope(_row_to_dict(updated))
