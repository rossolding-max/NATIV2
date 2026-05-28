"""Phase 1.5 — Brand Deals Capture REST endpoints.

Implements the M6 surface per ``docs/brand_deals_workflow.md``:

  - ``POST   /api/v1/talents/{talent_id}/brand-deals`` -> create deal
  - ``GET    /api/v1/talents/{talent_id}/brand-deals?outcome=...`` -> list
  - ``GET    /api/v1/brand-deals/{deal_id}`` -> fetch
  - ``PATCH  /api/v1/brand-deals/{deal_id}`` -> deep-merge JSONB
  - ``POST   /api/v1/brand-deals/{deal_id}/outcome`` -> set outcome enum
  - ``DELETE /api/v1/brand-deals/{deal_id}`` -> soft-delete

KPI honesty-floor enforcement runs server-side via
``app.services.kpi_validation`` on every POST + PATCH that touches KPIs.
Auto-link to ``talent.data.previous_brands[]`` runs on POST via
``BrandDealService.create_deal``.
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
from app.repositories.brand import BrandRepository
from app.repositories.brand_deal import BrandDealRepository
from app.repositories.talent import TalentRepository
from app.services.brand_deal_service import BrandDealService
from app.utils.logging import get_logger

log = get_logger(__name__)


# Two routers in this module so the URLs nest properly:
#   - Talent-scoped (``/talents/{talent_id}/brand-deals``) for create + list
#   - Top-level (``/brand-deals/{deal_id}``) for fetch + patch + outcome + delete
talent_scoped_router = APIRouter(prefix="/talents", tags=["brand-deals"])
top_level_router = APIRouter(prefix="/brand-deals", tags=["brand-deals"])


_VALID_OUTCOMES = (
    "pending",
    "successful_renewed",
    "successful",
    "mixed",
    "underperformed",
    "unfulfilled",
)


# ── Request models ───────────────────────────────────────────────────


class BrandDealCreate(BaseModel):
    """Free-form deal create. The service enforces server-authoritative fields."""

    model_config = ConfigDict(extra="allow")

    brand_name: str | None = None
    brand_id: str | None = None


class BrandDealPatch(BaseModel):
    """Generic JSONB patch — every field optional, server merges."""

    model_config = ConfigDict(extra="allow")


class OutcomeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(
        ..., pattern=r"^(pending|successful_renewed|successful|mixed|underperformed|unfulfilled)$"
    )


# ── Helpers ──────────────────────────────────────────────────────────


def _envelope(data: Any) -> APIResponse[Any]:
    return APIResponse[Any](data=data, meta=make_meta(), errors=[])


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "brand_deal_id": row.brand_deal_id,
        "talent_id": row.talent_id,
        "brand_id": row.brand_id,
        "outcome": row.outcome,
        "fee_usd": float(row.fee_usd) if row.fee_usd is not None else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "last_updated_at": row.last_updated_at.isoformat() if row.last_updated_at else None,
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


def _build_service(
    session: AsyncSession, *, agency_id: UUID | None
) -> tuple[BrandDealService, BrandDealRepository, TalentRepository, BrandRepository]:
    deals = BrandDealRepository(session, agency_id=agency_id)
    talents = TalentRepository(session, agency_id=agency_id)
    brands = BrandRepository(session, agency_id=agency_id or UUID(int=0))
    return BrandDealService(deals, talents, brands), deals, talents, brands


# ── Talent-scoped endpoints ──────────────────────────────────────────


@talent_scoped_router.post("/{talent_id}/brand-deals", status_code=http_status.HTTP_201_CREATED)
async def create_brand_deal(
    payload: BrandDealCreate,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Create a brand_deal + auto-link the matching previous_brands entry."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    service, _, _, _ = _build_service(session, agency_id=agency_id)
    created = await service.create_deal(
        talent_id, payload.model_dump(exclude_none=True), agency_id=agency_id
    )
    await session.commit()
    return _envelope(_row_to_dict(created))


@talent_scoped_router.get("/{talent_id}/brand-deals")
async def list_brand_deals_for_talent(
    request: Request,
    talent_id: str,
    outcome: str | None = Query(
        default=None,
        pattern=r"^(pending|successful_renewed|successful|mixed|underperformed|unfulfilled)$",
    ),
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """List all brand_deal rows for a talent, optionally filtered by outcome."""
    agency_id = _agency_id_from_request(request)
    repo = BrandDealRepository(session, agency_id=agency_id)
    rows = (
        await repo.find_by_outcome(talent_id, outcome)
        if outcome
        else await repo.find_by_talent(talent_id)
    )
    return _envelope([_row_to_dict(row) for row in rows])


# ── Top-level deal endpoints ─────────────────────────────────────────


@top_level_router.get("/{deal_id}")
async def get_brand_deal(
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = BrandDealRepository(session, agency_id=agency_id)
    row = await repo.get_by_id(deal_id)
    if row is None:
        raise NotFoundError(
            f"brand_deal {deal_id!r} not found",
            detail={"brand_deal_id": deal_id},
        )
    return _envelope(_row_to_dict(row))


@top_level_router.patch("/{deal_id}")
async def patch_brand_deal(
    payload: BrandDealPatch,
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Deep-merge JSONB. Honesty-floor re-validation runs in the service."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    service, _, _, _ = _build_service(session, agency_id=agency_id)
    diff = payload.model_dump(exclude_unset=True)
    updated = await service.patch_deal(deal_id, diff)
    await session.commit()
    return _envelope(_row_to_dict(updated))


@top_level_router.post("/{deal_id}/outcome")
async def set_brand_deal_outcome(
    payload: OutcomeUpdate,
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Set the indexed outcome column + JSONB mirror in one call."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    service, _, _, _ = _build_service(session, agency_id=agency_id)
    updated = await service.set_outcome(deal_id, payload.outcome)
    await session.commit()
    return _envelope(_row_to_dict(updated))


@top_level_router.delete("/{deal_id}")
async def soft_delete_brand_deal(
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Soft-delete (sets ``is_deleted=true``)."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = BrandDealRepository(session, agency_id=agency_id)
    # ``BaseRepository.soft_delete`` requires a deleted_by_agent_id; for v0.1
    # we tag every soft-delete with the agency-scoped agent placeholder.
    deleted = await repo.soft_delete(deal_id, deleted_by_agent_id="agency-default")
    await session.commit()
    return _envelope({"brand_deal_id": deleted.brand_deal_id, "is_deleted": True})
