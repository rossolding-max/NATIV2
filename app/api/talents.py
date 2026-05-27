"""Phase 1 — Talent Onboarding REST endpoints.

Implements the 10-step flow at ``docs/onboarding_workflow.md``. Same
endpoints power the CLI wizard shipped in Commit 3.

State machine: ``onboarding → active → archived`` (with re-open back to
``onboarding`` allowed). Per-patch validation is OFF; ``/activate`` runs
the full schema + cross-field guards.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import APIResponse, make_meta
from app.db.session import get_db
from app.errors import BusinessRuleError, NotFoundError, ValidationError
from app.repositories.talent import TalentRepository
from app.services import (
    brand_history_enrichment,
    contract_template_setup,
    questionnaire,
    similar_talent,
)
from app.services.platform_oauth import (
    SUPPORTED_PLATFORMS,
    OAuthStartResult,
    start_oauth_flow,
)
from app.services.talent_onboarding import (
    TalentOnboardingService,
    check_ready_for_activation,
    validate_data_against_schema,
)
from app.services.talent_seed import TalentSeedService
from app.utils.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/talents", tags=["talents"])


# ── Request models ───────────────────────────────────────────────────


class TalentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]*$")
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = None
    initial_platform_handle: str | None = None
    initial_platform_name: str | None = Field(
        default=None, description="Platform identifier matching the talent schema enum."
    )
    content_niches: list[str] | None = None


class PlatformOAuthStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    redirect_uri: str
    scopes: list[str] | None = None


class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pronouns: str | None = None
    contact: dict[str, Any] | None = None
    billing_entity: dict[str, Any] | None = None
    working_terms: dict[str, Any] | None = None
    brand_preferences: dict[str, Any] | None = None
    commission_override: dict[str, Any] | None = None
    invoice_payment_override: dict[str, Any] | None = None
    location: dict[str, Any] | None = None


class QuestionnaireAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    value: Any


class MediaPackExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    s3_keys: list[str] = Field(default_factory=list)
    run_llm_extraction: bool = False


class ResolveIndustryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: str


class AddSimilarTalentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    handles: list[str] = Field(default_factory=list)
    slug: str | None = None


class AdoptContractTemplateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starter_slug: str


class ContractTemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown_source: str | None = None
    merge_field_definitions: list[dict[str, Any]] | None = None
    clause_applicability_rules: list[dict[str, Any]] | None = None
    narrative_placeholders: list[dict[str, Any]] | None = None
    default_governing_law: str | None = None
    default_jurisdiction: str | None = None
    legal_reviewer_id: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────


def _envelope(data: Any) -> APIResponse[Any]:
    return APIResponse[Any](data=data, meta=make_meta(), errors=[])


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "talent_id": row.talent_id,
        "name": row.name,
        "status": row.status,
        "data": row.data,
    }


def _agency_id_from_request(request: Request) -> UUID | None:
    """Read app.state.agency_id, falling back to None for unbound dev."""
    value = getattr(request.app.state, "agency_id", None)
    if isinstance(value, UUID):
        return value
    return None


async def _get_talent_or_404(repo: TalentRepository, talent_id: str) -> Any:
    row = await repo.get_by_talent_id(talent_id)
    if row is None:
        raise NotFoundError(
            f"talent {talent_id!r} not found",
            detail={"talent_id": talent_id},
        )
    return row


def _warn_missing_idempotency(request: Request) -> None:
    if not request.headers.get("Idempotency-Key"):
        log.warning(
            "idempotency_key_missing_on_write",
            method=request.method,
            path=request.url.path,
        )


# ── Endpoints ────────────────────────────────────────────────────────


@router.post("", status_code=http_status.HTTP_201_CREATED)
async def create_talent(
    payload: TalentCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 1 — create the talent draft row."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    initial_platform: dict[str, str] | None = None
    if payload.initial_platform_handle and payload.initial_platform_name:
        initial_platform = {
            "platform": payload.initial_platform_name,
            "handle": payload.initial_platform_handle,
        }
    service = TalentSeedService(repo)
    talent = await service.create_seed(
        name=payload.name,
        slug=payload.slug,
        country=payload.country,
        timezone=payload.timezone,
        initial_platform=initial_platform,
        content_niches=payload.content_niches,
        agency_id=agency_id,
    )
    await session.commit()
    return _envelope(_row_to_dict(talent))


@router.get("")
async def list_talents(
    request: Request,
    status_filter: str | None = None,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """List talents (optionally filtered by status)."""
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    rows = (
        await repo.list_by_status(status_filter)
        if status_filter
        else await repo.list_by_agency(limit=200)
    )
    return _envelope([_row_to_dict(row) for row in rows])


@router.get("/{talent_id}")
async def get_talent(
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    row = await _get_talent_or_404(repo, talent_id)
    return _envelope(_row_to_dict(row))


@router.patch("/{talent_id}")
async def patch_talent(
    payload: AgentPatch,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 5-ish — generic talent.data patch (questionnaire answers, etc.)."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    await _get_talent_or_404(repo, talent_id)
    diff = payload.model_dump(exclude_none=True)
    service = TalentOnboardingService(repo)
    merged = await service.apply_data_patch(talent_id, diff)
    await session.commit()
    return _envelope({"data": merged})


@router.post("/{talent_id}/platforms/start-oauth")
async def start_oauth(
    payload: PlatformOAuthStart,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 2 — generate the authorize URL + persist state in Redis."""
    _warn_missing_idempotency(request)
    if payload.platform not in SUPPORTED_PLATFORMS:
        raise ValidationError(
            f"platform {payload.platform!r} not supported in v0.1",
            field="platform",
            detail={"supported": sorted(SUPPORTED_PLATFORMS)},
        )
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    await _get_talent_or_404(repo, talent_id)
    result: OAuthStartResult = await start_oauth_flow(
        talent_id=talent_id,
        platform=payload.platform,
        redirect_uri=payload.redirect_uri,
        scopes=payload.scopes,
        agency_id=agency_id,
    )
    return _envelope(
        {
            "authorize_url": result.authorize_url,
            "state": result.state,
            "platform": result.platform,
        }
    )


@router.post("/{talent_id}/media-pack/upload-url")
async def media_pack_upload_url(
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
    content_type: str = "application/pdf",
    filename: str = "media-pack.pdf",
) -> APIResponse[Any]:
    """Step 3a — presigned PUT URL for the agency to upload a media-pack file."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    await _get_talent_or_404(repo, talent_id)

    from app.utils.s3 import generate_presigned_put_url, public_object_url

    key = f"talent/{talent_id}/media-pack/{filename}"
    upload_url = generate_presigned_put_url(key=key, content_type=content_type)
    return _envelope(
        {
            "upload_url": upload_url,
            "public_url": public_object_url(key),
            "key": key,
            "content_type": content_type,
        }
    )


@router.post("/{talent_id}/media-pack/extract")
async def media_pack_extract(
    payload: MediaPackExtractRequest,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 3b — parse uploaded files + (optionally) run extractor agent."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    await _get_talent_or_404(repo, talent_id)

    from app.services.media_pack_extraction import extract_from_files

    result = await extract_from_files(
        talent_id,
        s3_keys=payload.s3_keys or None,
        run_llm_extraction=payload.run_llm_extraction,
    )
    return _envelope(
        {
            "talent_id": result.talent_id,
            "artefact_count": len(result.artefacts),
            "candidate_count": len(result.candidates),
            "candidates": [
                {
                    "field_path": c.field_path,
                    "value": c.value,
                    "confidence": c.confidence,
                    "source_artefact_id": c.source_artefact_id,
                }
                for c in result.candidates
            ],
            "errors": result.errors,
        }
    )


@router.post("/{talent_id}/questionnaire/next")
async def questionnaire_next(
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 5a — fetch the next unanswered question."""
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    row = await _get_talent_or_404(repo, talent_id)
    question = questionnaire.next_question(dict(row.data))
    if question is None:
        return _envelope({"complete": True})
    return _envelope(
        {
            "complete": False,
            "field_path": question.field_path,
            "prompt": question.prompt,
            "kind": question.kind,
            "required": question.required,
        }
    )


@router.post("/{talent_id}/questionnaire/answer")
async def questionnaire_answer(
    payload: QuestionnaireAnswer,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 5b — persist one questionnaire answer."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    await _get_talent_or_404(repo, talent_id)
    diff = questionnaire.build_patch_for_answer(payload.field_path, payload.value)
    service = TalentOnboardingService(repo)
    merged = await service.apply_data_patch(talent_id, diff)
    await session.commit()
    return _envelope({"data": merged})


@router.post("/{talent_id}/brands/resolve-industry")
async def resolve_brand_industry(
    payload: ResolveIndustryRequest,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 6 — infer industry for one brand name."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    await _get_talent_or_404(repo, talent_id)
    inference = await brand_history_enrichment.resolve_industry(payload.brand_name)
    return _envelope(
        {
            "brand_name": inference.brand_name,
            "industry_id": inference.industry_id,
            "confidence": inference.confidence,
            "source": inference.source,
        }
    )


@router.post("/{talent_id}/similar-talent")
async def add_similar_talent(
    payload: AddSimilarTalentRequest,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 7 — append a manual similar-talent seed."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    row = await _get_talent_or_404(repo, talent_id)

    seed = similar_talent.build_seed_entry(
        name=payload.name, handles=payload.handles, slug=payload.slug
    )
    updated_seeds = similar_talent.add_seed_to_data(dict(row.data), seed)
    service = TalentOnboardingService(repo)
    merged = await service.apply_data_patch(talent_id, {"similar_talent": updated_seeds})
    await session.commit()
    return _envelope({"data": merged, "added": seed})


@router.post("/{talent_id}/contract-template/adopt-starter")
async def adopt_starter(
    payload: AdoptContractTemplateRequest,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 7.5a — adopt one of the agency's starter contract templates."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    await _get_talent_or_404(repo, talent_id)
    starter = contract_template_setup.adopt_starter_template(payload.starter_slug)
    service = TalentOnboardingService(repo)
    merged = await service.apply_data_patch(talent_id, {"contract_template": starter})
    await session.commit()
    return _envelope({"data": merged})


@router.patch("/{talent_id}/contract-template")
async def patch_contract_template(
    payload: ContractTemplatePatch,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 7.5b — incremental contract-template edits; GAP-08 version bump."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    row = await _get_talent_or_404(repo, talent_id)
    current = dict(row.data.get("contract_template") or {})
    incoming = payload.model_dump(exclude_none=True)
    merged_template = contract_template_setup.materialise_contract_template_patch(
        current=current, incoming=incoming
    )
    service = TalentOnboardingService(repo)
    merged = await service.apply_data_patch(talent_id, {"contract_template": merged_template})
    await session.commit()
    return _envelope({"data": merged})


@router.post("/{talent_id}/activate")
async def activate(
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 8 — run full validation + flip to ``active``. Fires Step-9 task."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    row = await _get_talent_or_404(repo, talent_id)
    # Pre-flight validation surfaces nicer errors than the bare activate().
    try:
        validate_data_against_schema(dict(row.data))
        check_ready_for_activation(dict(row.data))
    except (BusinessRuleError, ValidationError):
        raise

    service = TalentOnboardingService(repo)
    new_status = await service.activate(talent_id)
    await session.commit()

    # Step 9 — fire the background research task (fire-and-forget).
    try:
        from app.celery_app import app as celery_app

        celery_app.send_task(
            "app.services.talent_background_research.kick_off_brand_discovery",
            args=[talent_id],
        )
    except Exception as exc:
        log.warning(
            "talent_background_research_enqueue_failed",
            talent_id=talent_id,
            error=str(exc),
        )

    return _envelope(
        {
            "status": new_status,
            "talent_id": talent_id,
            "activated_at": datetime.now(UTC).isoformat(),
        }
    )
