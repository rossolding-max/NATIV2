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
    run_llm_extraction: bool = True


class ReconcileDecisionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    action: str = Field(..., pattern=r"^(accept|edit|reject)$")
    edited_value: Any = None
    source_artefact_id: str | None = None


class ReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[ReconcileDecisionPayload]
    # Caller echoes the candidates back so the server doesn't need to
    # re-extract — keeps the endpoint stateless. Keyed by field_path.
    candidates: dict[str, Any] = Field(default_factory=dict)


class ResolveIndustryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: str


class AddSimilarTalentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    handles: list[str] = Field(default_factory=list)
    slug: str | None = None


class BulkTextRequest(BaseModel):
    """Free-text blob for the LLM-tidy bulk-parse endpoints."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1)


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


@router.post("/{talent_id}/reconcile")
async def reconcile(
    payload: ReconcileRequest,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 4 — apply operator decisions against Step-3 extraction candidates.

    Each decision is one of ``accept`` / ``edit`` / ``reject``. The
    accepted/edited values deep-merge into ``talent.data`` and an audit
    trail lands under ``data.extraction_provenance``.
    """
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    await _get_talent_or_404(repo, talent_id)

    from app.services.talent_reconciliation import (
        ReconciliationDecision,
        build_reconciliation_patch,
    )

    decisions = [
        ReconciliationDecision(
            field_path=d.field_path,
            action=d.action,  # type: ignore[arg-type]
            edited_value=d.edited_value,
            source_artefact_id=d.source_artefact_id,
        )
        for d in payload.decisions
    ]
    patch = build_reconciliation_patch(decisions, candidates_by_path=payload.candidates)
    if not patch:
        return _envelope({"applied": 0, "data": None})

    service = TalentOnboardingService(repo)
    merged = await service.apply_data_patch(talent_id, patch)
    await session.commit()
    return _envelope({"applied": len(decisions), "data": merged})


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
            "label": question.label,
            "kind": question.kind,
            "required": question.required,
            "choices_source": question.choices_source,
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


@router.post("/{talent_id}/brand-history/bulk")
async def brand_history_bulk(
    payload: BulkTextRequest,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 6 (bulk) — paste a free-text blob of past brand collaborations.

    An LLM parses + tidies into a clean list, then each entry passes
    through ``resolve_industry`` so the ``previous_brands[]`` array
    gets ``industry_id`` populated where the seed map / Exa lookup
    knows the answer.
    """
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    row = await _get_talent_or_404(repo, talent_id)

    names = await brand_history_enrichment.parse_name_list_from_text(payload.text, kind="brands")
    entries: list[dict[str, Any]] = []
    for name in names:
        inference = await brand_history_enrichment.resolve_industry(name)
        entry: dict[str, Any] = {"brand": name}
        if inference.industry_id is not None:
            entry["industry_id"] = inference.industry_id
            entry["industry_inference_source"] = inference.source
            entry["industry_inference_confidence"] = inference.confidence
        entries.append(entry)

    existing = list(row.data.get("previous_brands") or [])
    # Append-only merge — dedupe by lowercase brand name.
    seen = {str(e.get("brand", "")).strip().lower() for e in existing}
    new_entries = [e for e in entries if e["brand"].strip().lower() not in seen]
    merged_list = existing + new_entries

    service = TalentOnboardingService(repo)
    merged = await service.apply_data_patch(talent_id, {"previous_brands": merged_list})
    await session.commit()
    return _envelope(
        {
            "data": merged,
            "parsed_count": len(names),
            "added_count": len(new_entries),
            "entries": new_entries,
        }
    )


@router.post("/{talent_id}/similar-talent/bulk")
async def similar_talent_bulk(
    payload: BulkTextRequest,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 7 (bulk) — paste a free-text blob of comparable creators."""
    _warn_missing_idempotency(request)
    agency_id = _agency_id_from_request(request)
    repo = TalentRepository(session, agency_id=agency_id)
    row = await _get_talent_or_404(repo, talent_id)

    names = await brand_history_enrichment.parse_name_list_from_text(payload.text, kind="creators")
    existing = list(row.data.get("similar_talent") or [])
    seen = {str(s.get("id") or "").strip().lower() for s in existing}
    new_seeds: list[dict[str, Any]] = []
    for name in names:
        seed = similar_talent.build_seed_entry(name=name, handles=[])
        if seed["id"].strip().lower() in seen:
            continue
        seen.add(seed["id"].strip().lower())
        new_seeds.append(seed)
    merged_list = existing + new_seeds

    service = TalentOnboardingService(repo)
    merged = await service.apply_data_patch(talent_id, {"similar_talent": merged_list})
    await session.commit()
    return _envelope(
        {
            "data": merged,
            "parsed_count": len(names),
            "added_count": len(new_seeds),
            "entries": new_seeds,
        }
    )


@router.post("/{talent_id}/similar-talent")
async def add_similar_talent(
    payload: AddSimilarTalentRequest,
    request: Request,
    talent_id: str,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 7 — append a single manual similar-talent seed (kept for parity
    with the M5 REST surface; the wizard uses the /bulk endpoint).
    """
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
