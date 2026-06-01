"""Phase 3a — Brand Contacts REST endpoints.

Implements the M8 + M8.1 surface per ``docs/contact_enrichment_workflow.md``:

- ``GET    /api/v1/brands/{brand_id}/contacts``
  List enriched contacts (optional ``?decision_role=`` /
  ``?outreach_recommendation=`` / ``?revealed=`` /
  ``?qualification_tier=``).
- ``GET    /api/v1/talents/{talent_id}/pitchable-contacts``
  Filtered by DNC + 14-day per-talent cooldown.
- ``GET    /api/v1/brand-contacts/{contact_id}``                — fetch one
- ``PATCH  /api/v1/brand-contacts/{contact_id}``                — workflow patch
- ``POST   /api/v1/brands/{brand_id}/contact-enrichment/run``   — manual Phase A trigger
- ``POST   /api/v1/brands/{brand_id}/contact-emails/reveal``    — M8.1 Phase C bulk reveal

Phase A trigger enqueues
``app.services.contact_enrichment_task.kick_off_contact_enrichment``;
Phase C reveal enqueues
``app.services.contact_email_reveal_task.reveal_contact_emails``.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import APIResponse, make_meta
from app.db.session import get_db
from app.errors import NotFoundError
from app.repositories.brand import BrandRepository
from app.repositories.brand_contact import BrandContactRepository
from app.repositories.talent import TalentRepository
from app.utils.logging import get_logger

log = get_logger(__name__)


brand_scoped_router = APIRouter(prefix="/brands", tags=["brand-contacts"])
talent_scoped_router = APIRouter(prefix="/talents", tags=["brand-contacts"])
top_level_router = APIRouter(prefix="/brand-contacts", tags=["brand-contacts"])


_DECISION_ROLE_PATTERN = r"^(buyer|influencer|gatekeeper|champion|unknown)$"
_QUAL_TIER_PATTERN = r"^(qualified|speculative|unqualified)$"
_RECOMMENDATION_PATTERN = r"^(recommended|not_recommended|requires_review)$"


class ContactPatch(BaseModel):
    """Agent-driven workflow update."""

    model_config = ConfigDict(extra="allow")

    do_not_contact: bool | None = None
    do_not_contact_reason: str | None = None
    opt_out_at: str | None = None  # ISO-8601 stamp
    tags: list[str] | None = None
    notes: str | None = None


class TriggerEnrichmentBody(BaseModel):
    """Optional body for the POST /contact-enrichment/run endpoint."""

    talent_id: str | None = None
    target_titles: list[str] | None = Field(default=None, max_length=20)


class RevealEmailsBody(BaseModel):
    """Body for the M8.1 POST /contact-emails/reveal bulk endpoint.

    ``contact_ids`` is the operator-selected subset of the Phase A
    capture pool (typically 1-20 contacts at a time). Apollo has no
    bulk-match endpoint so the Celery task fans out sequentially at
    the 60/min rate-limit — 20 contacts ≈ 20 seconds.
    """

    contact_ids: list[str] = Field(..., min_length=1, max_length=50)


def _envelope(data: Any) -> APIResponse[Any]:
    return APIResponse[Any](data=data, meta=make_meta(), errors=[])


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "contact_id": row.contact_id,
        "brand_id": row.brand_id,
        "name": row.name,
        "decision_role": row.decision_role,
        # M8.1 — surface the new scalar fields on the wire so the UI
        # can render the broad-pool badge + the reveal state.
        "outreach_recommendation": row.outreach_recommendation,
        "revealed_at": row.revealed_at.isoformat() if row.revealed_at else None,
        "email": row.email,  # decrypted by EncryptedString TypeDecorator
        "do_not_contact": row.do_not_contact,
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


# ── Brand-scoped endpoints ───────────────────────────────────────────


@brand_scoped_router.get("/{brand_id}/contacts")
async def list_brand_contacts(
    request: Request,
    brand_id: str,
    decision_role: str | None = Query(default=None, pattern=_DECISION_ROLE_PATTERN),
    qualification_tier: str | None = Query(default=None, pattern=_QUAL_TIER_PATTERN),
    outreach_recommendation: str | None = Query(default=None, pattern=_RECOMMENDATION_PATTERN),
    revealed: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """List enriched contacts at a brand.

    Optional filters: ``decision_role``, ``qualification_tier``,
    ``outreach_recommendation`` (M8.1), ``revealed`` (M8.1 — true to
    show only contacts whose email has been revealed, false for the
    Phase A pool still pending operator review).
    """
    agency_id = _agency_id_from_request(request)
    repo = BrandContactRepository(session, agency_id=agency_id)
    rows = await repo.find_by_brand(brand_id)
    if decision_role:
        rows = [r for r in rows if r.decision_role == decision_role]
    if outreach_recommendation:
        rows = [r for r in rows if r.outreach_recommendation == outreach_recommendation]
    if revealed is True:
        rows = [r for r in rows if r.revealed_at is not None]
    elif revealed is False:
        rows = [r for r in rows if r.revealed_at is None]
    if qualification_tier:
        rows = [
            r
            for r in rows
            if (r.data or {}).get("qualification", {}).get("tier") == qualification_tier
        ]
    return _envelope([_row_to_dict(r) for r in rows])


@brand_scoped_router.post(
    "/{brand_id}/contact-enrichment/run", status_code=http_status.HTTP_202_ACCEPTED
)
async def trigger_contact_enrichment(
    request: Request,
    brand_id: str,
    payload: TriggerEnrichmentBody = Body(default_factory=TriggerEnrichmentBody),  # noqa: B008
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Manually enrich contacts for one brand. Returns 202 + Celery enqueue."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    # Brand is global — pass a zero UUID since the repo overrides
    # ``_base_filter`` to drop the agency_id constraint anyway.
    brands = BrandRepository(session, agency_id=agency_id or UUID(int=0))
    brand_row = await brands.get_by_id(brand_id)
    if brand_row is None:
        raise NotFoundError(f"brand {brand_id!r} not found", detail={"brand_id": brand_id})

    # If talent_id supplied, confirm + cross-check agency scope.
    if payload.talent_id:
        talents = TalentRepository(session, agency_id=agency_id)
        talent_row = await talents.get_by_talent_id(payload.talent_id)
        if talent_row is None:
            raise NotFoundError(
                f"talent {payload.talent_id!r} not found",
                detail={"talent_id": payload.talent_id},
            )

    # Fall back to the sentinel UUID when no agency context is bound to
    # the request (matches M6/M7 brand_deals + brand_candidates pattern).
    effective_agency = agency_id or UUID(int=0)

    from app.celery_app import app as celery_app

    enqueued = False
    try:
        celery_app.send_task(
            "app.services.contact_enrichment_task.kick_off_contact_enrichment",
            args=[brand_id, str(effective_agency), payload.talent_id, payload.target_titles],
        )
        enqueued = True
    except Exception as exc:
        log.warning("contact_enrichment_enqueue_failed", brand_id=brand_id, error=str(exc))

    return _envelope(
        {
            "brand_id": brand_id,
            "talent_id": payload.talent_id,
            "target_titles": payload.target_titles,
            "enqueued": enqueued,
            "task": "app.services.contact_enrichment_task.kick_off_contact_enrichment",
        }
    )


# ── M8.1 Phase C — bulk email reveal ─────────────────────────────────


@brand_scoped_router.post(
    "/{brand_id}/contact-emails/reveal", status_code=http_status.HTTP_202_ACCEPTED
)
async def reveal_contact_emails(
    request: Request,
    brand_id: str,
    payload: RevealEmailsBody = Body(...),  # noqa: B008
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Bulk-reveal Apollo emails for operator-selected contacts.

    Validates that every ``contact_id`` belongs to this brand, then
    enqueues
    ``app.services.contact_email_reveal_task.reveal_contact_emails``.
    Returns 202 immediately — the Celery task fans Apollo calls out
    sequentially.

    The strict honesty floor (verified/catchall only) is applied
    per-row inside Step 5b — invalid statuses still update
    ``revealed_at`` but leave ``email`` null so the UI shows we tried.
    """
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)

    # Validate the brand exists + every contact_id belongs to it.
    brands = BrandRepository(session, agency_id=agency_id or UUID(int=0))
    brand_row = await brands.get_by_id(brand_id)
    if brand_row is None:
        raise NotFoundError(f"brand {brand_id!r} not found", detail={"brand_id": brand_id})

    contacts_repo = BrandContactRepository(session, agency_id=agency_id)
    existing_rows = await contacts_repo.find_by_brand(brand_id)
    valid_ids = {r.contact_id for r in existing_rows}
    invalid = [cid for cid in payload.contact_ids if cid not in valid_ids]
    if invalid:
        raise NotFoundError(
            f"{len(invalid)} contact_id(s) not found at this brand",
            detail={"brand_id": brand_id, "invalid_contact_ids": invalid},
        )

    effective_agency = agency_id or UUID(int=0)

    from app.celery_app import app as celery_app

    enqueued = False
    try:
        celery_app.send_task(
            "app.services.contact_email_reveal_task.reveal_contact_emails",
            args=[brand_id, payload.contact_ids, str(effective_agency)],
        )
        enqueued = True
    except Exception as exc:
        log.warning("contact_email_reveal_enqueue_failed", brand_id=brand_id, error=str(exc))

    return _envelope(
        {
            "brand_id": brand_id,
            "contact_ids": payload.contact_ids,
            "requested": len(payload.contact_ids),
            "enqueued": enqueued,
            "task": "app.services.contact_email_reveal_task.reveal_contact_emails",
        }
    )


# ── Talent-scoped endpoints ──────────────────────────────────────────


@talent_scoped_router.get("/{talent_id}/pitchable-contacts")
async def list_pitchable_contacts(
    request: Request,
    talent_id: str,
    brand_id: str = Query(..., description="Brand to query contacts for"),
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Contacts at ``brand_id`` that this ``talent_id`` is allowed to pitch right now."""
    agency_id = _agency_id_from_request(request)
    talents = TalentRepository(session, agency_id=agency_id)
    talent_row = await talents.get_by_talent_id(talent_id)
    if talent_row is None:
        raise NotFoundError(f"talent {talent_id!r} not found", detail={"talent_id": talent_id})
    repo = BrandContactRepository(session, agency_id=agency_id)
    rows = await repo.find_pitchable_for_talent(talent_id, brand_id)
    return _envelope([_row_to_dict(r) for r in rows])


# ── Top-level contact endpoints ──────────────────────────────────────


@top_level_router.get("/{contact_id}")
async def get_brand_contact(
    request: Request,
    contact_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = BrandContactRepository(session, agency_id=agency_id)
    row = await repo.get_by_id(contact_id)
    if row is None:
        raise NotFoundError(
            f"brand_contact {contact_id!r} not found", detail={"contact_id": contact_id}
        )
    return _envelope(_row_to_dict(row))


@top_level_router.patch("/{contact_id}")
async def patch_brand_contact(
    payload: ContactPatch,
    request: Request,
    contact_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = BrandContactRepository(session, agency_id=agency_id)
    diff = payload.model_dump(exclude_none=True, exclude_unset=True)
    row = await repo.patch_workflow_state(contact_id, diff)
    await session.commit()
    return _envelope(_row_to_dict(row))
