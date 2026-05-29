"""Phase 4.5 — Discovery Prep Pack REST endpoints.

M11 surface per ``docs/discovery_prep_workflow.md``:

- ``GET    /api/v1/deals/{deal_id}/prep-pack``                (latest version)
- ``GET    /api/v1/deals/{deal_id}/prep-pack/versions``       (history)
- ``POST   /api/v1/deals/{deal_id}/prep-pack/generate``       (manual v1 trigger)
- ``POST   /api/v1/deals/{deal_id}/prep-pack/regenerate``     (NL feedback full-pack)

Manual generate validates ``substage="initial_call_scheduled"`` AND
``latest_prep_pack_id IS NULL``; regenerate looks up the current latest
version + enqueues a fresh dispatcher run with ``parent_version`` +
``regeneration_feedback`` threaded in.

Both 202-returning endpoints stamp ``data.prep_pack_enqueued_at`` so M10's
5-min cron debounce kicks in — manual + auto-fire stay mutually exclusive
within the 1-hour debounce window.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi import status as http_status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import APIResponse, make_meta
from app.db.session import get_db
from app.errors import BusinessRuleError, NotFoundError
from app.repositories.deal import DealRepository
from app.repositories.discovery_prep_pack import DiscoveryPrepPackRepository
from app.utils.logging import get_logger

log = get_logger(__name__)

top_level_router = APIRouter(prefix="/deals", tags=["prep_packs"])


class GenerateBody(BaseModel):
    """Body for ``POST /deals/{id}/prep-pack/generate``."""

    pre_generation_guidance: str | None = None
    by_agent_id: str = Field(default="agent_manual", min_length=1)


class RegenerateBody(BaseModel):
    """Body for ``POST /deals/{id}/prep-pack/regenerate``."""

    feedback: str = Field(min_length=1, max_length=4096)
    pre_generation_guidance: str | None = None
    by_agent_id: str = Field(default="agent_manual", min_length=1)


def _envelope(data: Any) -> APIResponse[Any]:
    return APIResponse[Any](data=data, meta=make_meta(), errors=[])


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


def _pack_to_dict(row: Any) -> dict[str, Any]:
    return {
        "prep_pack_id": row.prep_pack_id,
        "deal_id": row.deal_id,
        "version": row.version,
        "parent_version": row.parent_version,
        "is_latest": bool(row.is_latest),
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "data": row.data or {},
    }


def _version_summary(row: Any) -> dict[str, Any]:
    return {
        "prep_pack_id": row.prep_pack_id,
        "version": row.version,
        "parent_version": row.parent_version,
        "is_latest": bool(row.is_latest),
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "trigger": ((row.data or {}).get("generation") or {}).get("trigger"),
    }


# ── GET endpoints ───────────────────────────────────────────────────


@top_level_router.get("/{deal_id}/prep-pack")
async def get_latest_prep_pack(
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    prep_repo = DiscoveryPrepPackRepository(session, agency_id or UUID(int=0))
    row = await prep_repo.find_latest_for_deal(deal_id)
    if row is None:
        raise NotFoundError(
            f"no prep pack exists for deal {deal_id!r}",
            detail={"deal_id": deal_id},
        )
    return _envelope(_pack_to_dict(row))


@top_level_router.get("/{deal_id}/prep-pack/versions")
async def list_prep_pack_versions(
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    prep_repo = DiscoveryPrepPackRepository(session, agency_id or UUID(int=0))
    rows = await prep_repo.find_all_versions_for_deal(deal_id)
    return _envelope([_version_summary(r) for r in rows])


# ── POST endpoints ──────────────────────────────────────────────────


@top_level_router.post("/{deal_id}/prep-pack/generate", status_code=http_status.HTTP_202_ACCEPTED)
async def generate_prep_pack(
    payload: GenerateBody,
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Manual v1 trigger.

    Validates ``substage="initial_call_scheduled"`` AND no existing
    ``latest_prep_pack_id``. Enqueues the M2 dispatcher with
    ``pack_type="discovery_prep"`` and stamps ``data.prep_pack_enqueued_at``
    so the M10 cron's 1-hour debounce kicks in.
    """
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    deal_repo = DealRepository(session, agency_id=agency_id)
    deal = await deal_repo.get_by_id(deal_id)
    if deal is None:
        raise NotFoundError(f"deal {deal_id!r} not found", detail={"deal_id": deal_id})
    if deal.substage != "initial_call_scheduled":
        raise BusinessRuleError(
            (
                "prep packs can only generate when substage='initial_call_scheduled'; "
                f"current substage={deal.substage!r}"
            ),
            detail={"substage": deal.substage},
        )
    if deal.latest_prep_pack_id is not None:
        raise BusinessRuleError(
            ("this deal already has a prep pack; use the regenerate endpoint for a new version"),
            detail={"latest_prep_pack_id": deal.latest_prep_pack_id},
        )

    effective_agency = agency_id or UUID(int=0)
    from app.celery_app import app as celery_app

    enqueued = False
    try:
        celery_app.send_task(
            "app.tasks.pack_generation.generate_pack",
            kwargs={
                "pack_type": "discovery_prep",
                "deal_id": deal_id,
                "agency_id": str(effective_agency),
                "agent_id": payload.by_agent_id,
                "pre_generation_guidance": payload.pre_generation_guidance,
            },
        )
        enqueued = True
    except Exception as exc:
        log.warning(
            "prep_pack_generate_enqueue_failed",
            deal_id=deal_id,
            error=str(exc),
        )

    # Stamp the M10 debounce so the cron skips this deal for 1 hour.
    data = dict(deal.data or {})
    data["prep_pack_enqueued_at"] = datetime.now(UTC).isoformat()
    deal.data = data
    await session.flush()
    await session.commit()

    return _envelope(
        {
            "enqueued": enqueued,
            "deal_id": deal_id,
            "by_agent_id": payload.by_agent_id,
            "task": "app.tasks.pack_generation.generate_pack",
            "pack_type": "discovery_prep",
        }
    )


@top_level_router.post("/{deal_id}/prep-pack/regenerate", status_code=http_status.HTTP_202_ACCEPTED)
async def regenerate_prep_pack(
    payload: RegenerateBody,
    request: Request,
    deal_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Full-pack regen with natural-language feedback.

    Looks up the latest version + threads its ``version`` as
    ``parent_version`` into the dispatcher. Section-targeted regen
    (``target_sections[]``) defers to M11.1.
    """
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    prep_repo = DiscoveryPrepPackRepository(session, agency_id or UUID(int=0))
    latest = await prep_repo.find_latest_for_deal(deal_id)
    if latest is None:
        raise NotFoundError(
            (
                f"no existing prep pack to regenerate for deal {deal_id!r}; use the "
                "generate endpoint first"
            ),
            detail={"deal_id": deal_id},
        )

    effective_agency = agency_id or UUID(int=0)
    from app.celery_app import app as celery_app

    enqueued = False
    try:
        celery_app.send_task(
            "app.tasks.pack_generation.generate_pack",
            kwargs={
                "pack_type": "discovery_prep",
                "deal_id": deal_id,
                "agency_id": str(effective_agency),
                "agent_id": payload.by_agent_id,
                "pre_generation_guidance": payload.pre_generation_guidance,
                "regeneration_feedback": payload.feedback,
                "parent_version": latest.version,
            },
        )
        enqueued = True
    except Exception as exc:
        log.warning(
            "prep_pack_regenerate_enqueue_failed",
            deal_id=deal_id,
            error=str(exc),
        )

    # Stamp the debounce stamp on the deal so cron skips.
    deal_repo = DealRepository(session, agency_id=agency_id)
    deal = await deal_repo.get_by_id(deal_id)
    if deal is not None:
        data = dict(deal.data or {})
        data["prep_pack_enqueued_at"] = datetime.now(UTC).isoformat()
        deal.data = data
        await session.flush()
        await session.commit()

    return _envelope(
        {
            "enqueued": enqueued,
            "deal_id": deal_id,
            "parent_version": latest.version,
            "by_agent_id": payload.by_agent_id,
            "feedback_excerpt": payload.feedback[:120],
            "task": "app.tasks.pack_generation.generate_pack",
            "pack_type": "discovery_prep",
        }
    )
