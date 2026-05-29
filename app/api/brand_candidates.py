"""Phase 2 — Brand Candidates REST endpoints.

Implements the M7 surface per ``docs/brand_discovery.md``:

  - ``GET    /api/v1/talents/{talent_id}/brand-candidates``  -> list (optional ?tier=)
  - ``GET    /api/v1/brand-candidates/{candidate_id}``       -> fetch
  - ``PATCH  /api/v1/brand-candidates/{candidate_id}``       -> workflow patch
  - ``POST   /api/v1/talents/{talent_id}/brand-discovery/run`` -> manual rerun
  - ``GET    /api/v1/brand-discovery/searches``              -> catalog (M7.1)

The manual rerun enqueues the same Celery task that ``/activate`` fires
(``app.services.talent_background_research.kick_off_brand_discovery``).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import APIResponse, make_meta
from app.db.session import get_db
from app.errors import NotFoundError, ValidationError
from app.repositories.brand_candidate import BrandCandidateRepository
from app.repositories.talent import TalentRepository
from app.services.discovery.catalog import (
    KNOWN_SEARCH_NAMES,
    SEARCH_CATALOG,
    validate_search_names,
)
from app.utils.logging import get_logger

log = get_logger(__name__)


# Three routers — talent-scoped list/rerun + top-level deal-id addressing
# + the discovery-catalog endpoint.
talent_scoped_router = APIRouter(prefix="/talents", tags=["brand-candidates"])
top_level_router = APIRouter(prefix="/brand-candidates", tags=["brand-candidates"])
discovery_router = APIRouter(prefix="/brand-discovery", tags=["brand-candidates"])


_TIER_PATTERN = r"^(re-engage|primary|secondary|tertiary|emerging)$"
_STATUS_PATTERN = r"^(new|shortlisted|pitched|responded|negotiating|closed_won|closed_lost|parked)$"
_QUALIFICATION_PATTERN = (
    r"^((qualified|speculative|unqualified)"
    r"(,(qualified|speculative|unqualified))*|all)$"
)
_DEFAULT_QUALIFICATION_FILTER = "all"


# ── Request models ───────────────────────────────────────────────────


class CandidatePatch(BaseModel):
    """Agent-driven workflow update — status / assigned_to / notes / pitch_history."""

    model_config = ConfigDict(extra="allow")

    status: str | None = Field(default=None, pattern=_STATUS_PATTERN)
    assigned_to: str | None = None
    user_notes: str | None = None


class TriggerDiscoveryBody(BaseModel):
    """Optional body for ``POST /brand-discovery/run``.

    ``searches=None`` or omitting the field runs every search in the
    catalog (default). ``searches=[...]`` narrows the run to those
    names; unknown names get a 422.

    M7.7 — ``mode`` selects v2 architecture path:
      - "maintenance" (default): Phase 3 + Phase 4 only. Cheap.
        Uses the talent's existing seed map; no Phase 1.5 review.
      - "full_build": Phase 1 industry compilation + persisted
        IndustryReview for human review. The operator must approve
        the review at /industry-review/approve to trigger Phase 2.
    """

    searches: list[str] | None = None
    mode: Literal["full_build", "maintenance"] = "maintenance"


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


def _parse_qualification_filter(value: str) -> set[str] | None:
    """Parse the ``?qualification=`` query value into a set or None for ``all``.

    ``all`` returns None signalling no filter. The regex pattern on the
    Query already rejects unknown tokens, so by here we only need to
    split + return.
    """
    if value == "all":
        return None
    return {token.strip() for token in value.split(",") if token.strip()}


def _row_qualification_tier(row: Any) -> str:
    """Pull the qualification tier from a brand_candidate row's JSONB data.

    Returns ``"unqualified"`` when the data block is missing the
    expected ``qualification.tier`` shape — conservative default so the
    row gets filtered out of the default ``qualified,speculative`` view
    (matching v0.1 behaviour for malformed rows).
    """
    data = row.data or {}
    qual = data.get("qualification") if isinstance(data, dict) else None
    if isinstance(qual, dict):
        tier = qual.get("tier")
        if isinstance(tier, str):
            return tier
    return "unqualified"


# ── Talent-scoped endpoints ──────────────────────────────────────────


@talent_scoped_router.get("/{talent_id}/brand-candidates")
async def list_brand_candidates(
    request: Request,
    talent_id: str,
    tier: str | None = Query(default=None, pattern=_TIER_PATTERN),
    qualification: str = Query(
        default=_DEFAULT_QUALIFICATION_FILTER, pattern=_QUALIFICATION_PATTERN
    ),
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """List candidates for a talent.

    Optional filters:
    - ``?tier=primary|secondary|tertiary|re-engage|emerging``
    - ``?qualification=qualified,speculative,unqualified,all`` —
      defaults to ``qualified,speculative`` so today's behaviour is
      preserved. Pass ``all`` to surface the long tail including the
      lowest-confidence emerging brands; pass a comma-separated subset
      for finer control.
    """
    agency_id = _agency_id_from_request(request)
    repo = BrandCandidateRepository(session, agency_id=agency_id)
    rows = (
        await repo.find_by_tier(talent_id, tier) if tier else await repo.find_by_talent(talent_id)
    )

    allowed_qualifications = _parse_qualification_filter(qualification)
    if allowed_qualifications is not None:
        rows = [r for r in rows if _row_qualification_tier(r) in allowed_qualifications]

    return _envelope([_row_to_dict(row) for row in rows])


@talent_scoped_router.post(
    "/{talent_id}/brand-discovery/run", status_code=http_status.HTTP_202_ACCEPTED
)
async def trigger_brand_discovery(
    request: Request,
    talent_id: str,
    payload: TriggerDiscoveryBody = Body(default_factory=TriggerDiscoveryBody),  # noqa: B008
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Manually re-run discovery for this talent.

    Confirms the talent exists, validates any caller-supplied
    ``searches`` against the catalog, then enqueues the same Celery
    task that M5's ``/activate`` fires. Returns 202 (Accepted)
    immediately — the task runs in the background.
    """
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    row = await repo.get_by_talent_id(talent_id)
    if row is None:
        raise NotFoundError(f"talent {talent_id!r} not found", detail={"talent_id": talent_id})

    enabled_searches: list[str] | None = None
    if payload.searches is not None:
        unknown = validate_search_names(payload.searches)
        if unknown:
            raise ValidationError(
                f"unknown search name(s): {unknown}",
                detail={"unknown": unknown, "known": sorted(KNOWN_SEARCH_NAMES)},
            )
        # Dedupe while preserving order.
        enabled_searches = list(dict.fromkeys(payload.searches))
        if not enabled_searches:
            raise ValidationError(
                "searches list cannot be empty — omit the field to run all",
                detail={"searches": []},
            )

    from app.celery_app import app as celery_app
    from app.config import settings

    # Fall back to the sentinel UUID when no agency is bound to the
    # request (matches M8 trigger + brand-deals endpoints).
    effective_agency = agency_id or UUID(int=0)

    # M7.7 — full_build mode runs Phase 1 synchronously, persists the
    # IndustryReview, then returns 202 pointing at the review URL.
    # The operator must explicitly approve at /industry-review/approve
    # to trigger Phase 2.
    if payload.mode == "full_build" and settings.discovery_v2_enabled:
        return await _trigger_v2_full_build(
            talent_id=talent_id,
            agency_id=effective_agency,
            talent_row=row,
            session=session,
        )

    enqueued = False
    try:
        celery_app.send_task(
            "app.services.talent_background_research.kick_off_brand_discovery",
            args=[talent_id, str(effective_agency), enabled_searches],
        )
        enqueued = True
    except Exception as exc:
        log.warning("brand_discovery_enqueue_failed", talent_id=talent_id, error=str(exc))

    return _envelope(
        {
            "talent_id": talent_id,
            "mode": payload.mode,
            "enqueued": enqueued,
            "task": "app.services.talent_background_research.kick_off_brand_discovery",
            "enabled_searches": enabled_searches,  # echoes None when running all
        }
    )


async def _trigger_v2_full_build(
    *,
    talent_id: str,
    agency_id: UUID,
    talent_row: Any,
    session: AsyncSession,
) -> APIResponse[Any]:
    """Run Phase 1 inline, persist IndustryReview, return pointer to review URL."""
    from app.repositories.industry_review import IndustryReviewRepository
    from app.services.discovery.phase_1_industry_compilation import (
        compile_industry_universe,
    )
    from app.utils.taxonomies import get_taxonomies

    pairs = await compile_industry_universe(
        talent_data=dict(talent_row.data or {}),
        brand_deals=[],  # full_build only uses talent_data; deals fold in at Phase 2/3
        taxonomies=get_taxonomies(),
    )
    items: list[dict[str, Any]] = []
    for winner, alternates in pairs:
        items.append(
            {
                "industry_id": winner.industry_id,
                "rationale": winner.rationale,
                "source": winner.source,
                "approved": True,
                "alternate_rationales": [
                    {"source": a.source, "rationale": a.rationale} for a in alternates
                ],
            }
        )

    reviews = IndustryReviewRepository(session, agency_id=agency_id)
    review = await reviews.create_pending(talent_id=talent_id, items=items)
    await session.commit()

    return _envelope(
        {
            "talent_id": talent_id,
            "mode": "full_build",
            "phase": "1_complete",
            "review_id": review.review_id,
            "review_url": f"/api/v1/talents/{talent_id}/industry-review",
            "approve_url": f"/api/v1/talents/{talent_id}/industry-review/approve",
            "proposed_industry_count": len(items),
        }
    )


# ── Discovery catalog ────────────────────────────────────────────────


@discovery_router.get("/searches")
async def list_discovery_searches() -> APIResponse[Any]:
    """Return the 16-search catalog so a UI can render a picker."""
    items = [
        {
            "name": s.name,
            "label": s.label,
            "description": s.description,
            "weight": s.weight,
            "requires_llm": s.requires_llm,
            "requires_external_skill": s.requires_external_skill,
        }
        for s in SEARCH_CATALOG
    ]
    return _envelope(items)


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
