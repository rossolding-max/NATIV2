"""Phase 4 — Deal Lifecycle REST endpoints.

Implements the M10 surface per ``docs/deal_lifecycle_workflow.md``:

- ``GET    /api/v1/talents/{talent_id}/deals``           (optional stage/substage/include_terminal)
- ``GET    /api/v1/brands/{brand_id}/deals``
- ``GET    /api/v1/deals/due-for-action``                (optional ``?talent_id=``)
- ``GET    /api/v1/deals/{deal_id}``                     (full nested record)
- ``GET    /api/v1/deals/{deal_id}/stage-history``       (audit log only)
- ``POST   /api/v1/deals``                               (manual create -> lead/new_lead)
- ``PATCH  /api/v1/deals/{deal_id}``                     (workflow patch; refuses stage/substage)
- ``POST   /api/v1/deals/{deal_id}/transition``          (state-machine entry)
- ``POST   /api/v1/deals/{deal_id}/loss``                (structured loss capture)

The transition endpoint returns the full chain so the UI can show both
the requested step and any auto-advance follow-on (e.g. agent sets
``qualified``; response shows ``[qualified, proposal_drafting]``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import APIResponse, make_meta
from app.db.session import get_db
from app.errors import NotFoundError, ValidationError
from app.repositories.deal import DealRepository
from app.services.deal_lifecycle import orchestrator
from app.utils.logging import get_logger

log = get_logger(__name__)


brand_scoped_router = APIRouter(prefix="/brands", tags=["deals"])
talent_scoped_router = APIRouter(prefix="/talents", tags=["deals"])
top_level_router = APIRouter(prefix="/deals", tags=["deals"])


_STAGE_PATTERN = r"^(lead|proposal|contract|delivery|close|archived)$"


class DealCreate(BaseModel):
    """Body for ``POST /deals`` — manual creation."""

    talent_id: str = Field(min_length=1)
    brand_id: str = Field(min_length=1)
    primary_contact_id: str | None = None
    by_agent_id: str = Field(default="agent_manual", min_length=1)
    opening_note: str | None = None


class DealPatch(BaseModel):
    """Workflow patch — refuses ``stage`` / ``substage`` (use /transition)."""

    model_config = ConfigDict(extra="allow")

    user_notes: str | None = None
    next_action_due_at: datetime | None = None
    expected_value_usd: float | None = None
    expected_close_date: datetime | None = None
    primary_contact_id: str | None = None
    data: dict[str, Any] | None = None


class TransitionBody(BaseModel):
    """Body for ``POST /deals/{id}/transition``."""

    target_substage: str = Field(min_length=1)
    by_agent_id: str = Field(default="agent_manual", min_length=1)
    note: str | None = None


class LossBody(BaseModel):
    """Body for ``POST /deals/{id}/loss``."""

    reason: str = Field(min_length=1)
    lost_at_stage: str | None = Field(default=None, pattern=_STAGE_PATTERN)
    competitor_brand: str | None = None
    notes: str | None = None
    by_agent_id: str = Field(default="agent_manual", min_length=1)


def _envelope(data: Any) -> APIResponse[Any]:
    return APIResponse[Any](data=data, meta=make_meta(), errors=[])


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "deal_id": row.deal_id,
        "talent_id": row.talent_id,
        "brand_id": row.brand_id,
        "primary_contact_id": row.primary_contact_id,
        "originating_enrollment_id": row.originating_enrollment_id,
        "stage": row.stage,
        "substage": row.substage,
        "is_terminal": bool(row.is_terminal),
        "is_won": bool(row.is_won),
        "expected_value_usd": (
            float(row.expected_value_usd) if row.expected_value_usd is not None else None
        ),
        "expected_close_date": (
            row.expected_close_date.isoformat() if row.expected_close_date else None
        ),
        "next_action_due_at": (
            row.next_action_due_at.isoformat() if row.next_action_due_at else None
        ),
        "latest_prep_pack_id": row.latest_prep_pack_id,
        "latest_proposal_pack_id": row.latest_proposal_pack_id,
        "latest_contract_pack_id": row.latest_contract_pack_id,
        "latest_performance_report_pack_id": row.latest_performance_report_pack_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "data": row.data or {},
    }


def _step_to_dict(step: Any) -> dict[str, Any]:
    return {
        "stage": step.stage,
        "substage": step.substage,
        "by_agent_id": step.by_agent_id,
        "note": step.note,
        "is_auto_advance": step.is_auto_advance,
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


@talent_scoped_router.get("/{talent_id}/deals")
async def list_deals_by_talent(
    request: Request,
    talent_id: str,
    stage: str | None = Query(default=None, pattern=_STAGE_PATTERN),
    substage: str | None = Query(default=None),
    include_terminal: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = DealRepository(session, agency_id=agency_id)
    rows = await repo.find_by_talent(
        talent_id,
        stage=stage,
        substage=substage,
        include_terminal=include_terminal,
    )
    return _envelope([_row_to_dict(r) for r in rows])


# ── Brand-scoped endpoints ──────────────────────────────────────────


@brand_scoped_router.get("/{brand_id}/deals")
async def list_deals_by_brand(
    request: Request,
    brand_id: str,
    include_terminal: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = DealRepository(session, agency_id=agency_id)
    rows = await repo.find_by_brand(brand_id, include_terminal=include_terminal)
    return _envelope([_row_to_dict(r) for r in rows])


# ── Top-level deal endpoints ────────────────────────────────────────


@top_level_router.get("/due-for-action")
async def list_deals_due_for_action(
    request: Request,
    talent_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = DealRepository(session, agency_id=agency_id)
    rows = await repo.find_due_for_action(_now(), talent_id=talent_id)
    return _envelope([_row_to_dict(r) for r in rows])


@top_level_router.get("/{deal_id}")
async def get_deal(
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = DealRepository(session, agency_id=agency_id)
    row = await repo.get_by_id(deal_id)
    if row is None:
        raise NotFoundError(f"deal {deal_id!r} not found", detail={"deal_id": deal_id})
    return _envelope(_row_to_dict(row))


@top_level_router.get("/{deal_id}/stage-history")
async def get_stage_history(
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = DealRepository(session, agency_id=agency_id)
    row = await repo.get_by_id(deal_id)
    if row is None:
        raise NotFoundError(f"deal {deal_id!r} not found", detail={"deal_id": deal_id})
    history = (row.data or {}).get("stage_history") or []
    return _envelope(
        {
            "deal_id": deal_id,
            "stage": row.stage,
            "substage": row.substage,
            "is_terminal": bool(row.is_terminal),
            "is_won": bool(row.is_won),
            "history": list(history),
        }
    )


@top_level_router.post("", status_code=http_status.HTTP_201_CREATED)
async def create_deal(
    payload: DealCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Manual deal creation. Lands in ``lead / new_lead`` with an opening
    audit entry. M9's automatic creation on ``interested`` reply remains
    the primary writer; this is for "agent sees opportunity directly".
    """
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = DealRepository(session, agency_id=agency_id)
    row = await repo.insert_manual_deal(
        talent_id=payload.talent_id,
        brand_id=payload.brand_id,
        primary_contact_id=payload.primary_contact_id,
        by_agent_id=payload.by_agent_id,
        opening_note=payload.opening_note,
    )
    await session.commit()
    return _envelope(_row_to_dict(row))


@top_level_router.patch("/{deal_id}")
async def patch_deal(
    payload: DealPatch,
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = DealRepository(session, agency_id=agency_id)
    diff = payload.model_dump(exclude_none=True, exclude_unset=True)
    row = await repo.patch_workflow_state(deal_id, diff)
    await session.commit()
    return _envelope(_row_to_dict(row))


@top_level_router.post("/{deal_id}/transition", status_code=http_status.HTTP_200_OK)
async def transition_deal(
    payload: TransitionBody,
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Apply a state-machine transition. Chains auto-advance follow-ons
    in a single call (qualified -> proposal_drafting, etc.) and returns
    the full chain so the UI can show both steps."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = DealRepository(session, agency_id=agency_id)
    deal = await repo.get_by_id(deal_id)
    if deal is None:
        raise NotFoundError(f"deal {deal_id!r} not found", detail={"deal_id": deal_id})

    plan = orchestrator.apply_transition(
        deal=deal,
        target_substage=payload.target_substage,
        by_agent_id=payload.by_agent_id,
        note=payload.note,
    )
    await session.flush()
    await session.refresh(deal)
    await session.commit()

    return _envelope(
        {
            "deal": _row_to_dict(deal),
            "chain": [_step_to_dict(step) for step in plan.steps],
            "final_is_terminal": plan.final_is_terminal,
            "final_is_won": plan.final_is_won,
        }
    )


@top_level_router.post("/{deal_id}/loss", status_code=http_status.HTTP_200_OK)
async def record_deal_loss(
    payload: LossBody,
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Structured loss capture. Writes ``data.loss`` block + transitions
    to ``lost``. The PATCH endpoint refuses ``substage="lost"`` so all
    loss flows route through here."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = DealRepository(session, agency_id=agency_id)
    deal = await repo.get_by_id(deal_id)
    if deal is None:
        raise NotFoundError(f"deal {deal_id!r} not found", detail={"deal_id": deal_id})

    try:
        plan = orchestrator.record_loss(
            deal=deal,
            reason=payload.reason,
            by_agent_id=payload.by_agent_id,
            lost_at_stage=payload.lost_at_stage,
            competitor_brand=payload.competitor_brand,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise ValidationError(str(exc), detail={"reason": payload.reason}) from exc
    await session.flush()
    await session.refresh(deal)
    await session.commit()

    return _envelope(
        {
            "deal": _row_to_dict(deal),
            "chain": [_step_to_dict(step) for step in plan.steps],
            "loss": (deal.data or {}).get("loss"),
        }
    )


def _now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
