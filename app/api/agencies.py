"""Phase 0 — Agency Setup REST endpoints.

Implements the 9-step setup flow documented in
``docs/agency_setup_workflow.md`` as a sequence of focused REST endpoints.
The same surface is consumed by the interactive CLI wizard (PR 3).

Endpoints are intentionally narrow: one resource path per step. State
transitions are owned by ``AgencySetupService``; vendor calls by the
existing M3 ``SmartleadClient``; DNS validation by
``app.services.dns_validation``.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request
from fastapi import status as http_status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import APIResponse, make_meta
from app.db.session import get_db
from app.errors import BusinessRuleError, NotFoundError, ValidationError
from app.repositories.agency_profile import AgencyProfileRepository
from app.services import dns_validation
from app.services.agency_setup import (
    AgencySetupService,
    validate_data_against_schema,
)
from app.services.branding import (
    generate_presigned_logo_put_url,
    validate_logo_metadata,
)
from app.services.invoice_template import (
    STARTER_TEMPLATE_MARKDOWN,
    materialise_invoice_template_patch,
)
from app.utils.logging import get_logger
from app.vendors.smartlead import SmartleadClient

log = get_logger(__name__)
router = APIRouter(prefix="/agencies", tags=["agencies"])


# ── Request models ───────────────────────────────────────────────────


class AgencyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agency_slug: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]*$", min_length=2, max_length=64)
    name: str = Field(..., min_length=1, max_length=200)
    domain: str = Field(..., min_length=3, max_length=253)
    website_url: str | None = None
    company_address: str = Field(..., min_length=1)


class BrandingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logo_url: str | None = None
    logo_dark_url: str | None = None
    primary_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    accent_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    background_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    text_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    font_family_heading: str | None = None
    font_family_body: str | None = None
    google_fonts: list[str] | None = None
    tagline: str | None = None
    deck_template_id: str | None = None


class LogoUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: str
    size_bytes: int | None = None


class AgentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(..., min_length=1)
    email: EmailStr
    phone: str | None = None
    title: str | None = None
    linkedin_url: str | None = None


class DnsRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dkim_selector: str = "smartlead"


class MailboxProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    mailbox_address: EmailStr
    smtp_host: str
    smtp_port: int = Field(..., ge=1, le=65535)
    smtp_username: str
    smtp_password: str
    imap_host: str
    imap_port: int = Field(..., ge=1, le=65535)
    daily_send_cap: int = Field(50, ge=10, le=500)


class SignaturePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_signature_template: str = Field(..., min_length=1)


class InvoiceTemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown_source: str | None = None
    invoice_number_prefix: str | None = None
    invoice_number_format: str | None = None
    default_payment_terms_days: int | None = Field(None, ge=0, le=365)
    due_date_calculation: str | None = None
    tax_handling: str | None = None
    default_tax_rate: float | None = Field(None, ge=0.0, le=1.0)
    tax_label: str | None = None
    payment_instructions_markdown: str | None = None
    invoice_footer: str | None = None


class CommissionDefaultsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_commission_rate: float = Field(..., ge=0.0, le=1.0)
    default_commission_model: str


# ── Helpers ──────────────────────────────────────────────────────────


def _require_agency_id_header_warning(request: Request) -> None:
    """Soft-warn when an idempotency key is missing on writes.

    v0.1 doesn't yet back idempotency keys with storage. Logging at the
    boundary makes it easy to grep for callers that need to be upgraded
    when the full backing lands.
    """
    if not request.headers.get("Idempotency-Key"):
        log.warning(
            "idempotency_key_missing_on_write",
            method=request.method,
            path=request.url.path,
        )


async def _get_singleton_or_404(
    session: AsyncSession,
) -> Any:
    repo = AgencyProfileRepository(session)
    row = await repo.get_singleton()
    if row is None:
        raise NotFoundError("agency_profile singleton not found — call POST /agencies first")
    return row


def _envelope(data: Any) -> APIResponse[Any]:
    return APIResponse[Any](data=data, meta=make_meta(), errors=[])


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "agency_id": str(row.agency_id),
        "name": row.name,
        "status": row.status,
        "data": row.data,
    }


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("/me", status_code=http_status.HTTP_200_OK)
async def get_me(session: AsyncSession = Depends(get_db)) -> APIResponse[Any]:  # noqa: B008
    """Return the singleton ``agency_profile`` row (or 404)."""
    row = await _get_singleton_or_404(session)
    return _envelope(_row_to_dict(row))


@router.post("", status_code=http_status.HTTP_201_CREATED)
async def create_agency(
    payload: AgencyCreate,
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 1 — create the singleton agency_profile row."""
    _require_agency_id_header_warning(request)
    agency_uuid = uuid4()
    repo = AgencyProfileRepository(session)
    initial_data: dict[str, Any] = {
        "agency_id": payload.agency_slug,
        "name": payload.name,
        "domain": payload.domain,
        "company_address": payload.company_address,
    }
    if payload.website_url:
        initial_data["website_url"] = payload.website_url
    row = await repo.create_singleton(
        agency_id=agency_uuid, name=payload.name, initial_data=initial_data
    )
    await session.commit()
    # Bind the singleton onto app.state so subsequent requests pick it up
    # without a process restart.
    request.app.state.agency_id = agency_uuid
    return _envelope(_row_to_dict(row))


@router.patch("/me/branding")
async def patch_branding(
    payload: BrandingPatch,
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 1.5 — write the ``branding`` block."""
    _require_agency_id_header_warning(request)
    row = await _get_singleton_or_404(session)
    diff = {"branding": payload.model_dump(exclude_none=True)}
    service = AgencySetupService(AgencyProfileRepository(session))
    merged = await service.apply_data_patch(row.agency_id, diff)
    await session.commit()
    return _envelope({"data": merged})


@router.post("/me/branding/logo-upload-url")
async def request_logo_upload_url(
    payload: LogoUploadRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 1.5 helper — issue a presigned PUT URL for the logo upload."""
    _require_agency_id_header_warning(request)
    row = await _get_singleton_or_404(session)
    validate_logo_metadata(
        content_type=payload.content_type, declared_size_bytes=payload.size_bytes
    )
    presigned = generate_presigned_logo_put_url(
        agency_id=row.agency_id,
        content_type=payload.content_type,
        declared_size_bytes=payload.size_bytes,
    )
    return _envelope(presigned)


@router.patch("/me/agent")
async def patch_agent(
    payload: AgentPatch,
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 2 — write the (single, v0.1) named agent."""
    _require_agency_id_header_warning(request)
    row = await _get_singleton_or_404(session)
    agent_record = payload.model_dump(exclude_none=True)
    agent_record["is_primary"] = True
    agent_record["represents_talent_ids"] = []
    diff = {"agents": [agent_record]}
    service = AgencySetupService(AgencyProfileRepository(session))
    merged = await service.apply_data_patch(row.agency_id, diff)
    await session.commit()
    return _envelope({"data": merged})


@router.post("/me/dns/refresh")
async def refresh_dns_status(
    payload: DnsRefreshRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 3 — query DNS for SPF/DKIM/DMARC and persist the result.

    Smartlead does NOT expose a DNS-verification API; M4 looks up TXT
    records directly via dnspython (see ``app/services/dns_validation``).
    The result is stored under ``sending_mailboxes[0].dns_records`` +
    ``.dns_records_verified``.
    """
    _require_agency_id_header_warning(request)
    row = await _get_singleton_or_404(session)
    data = dict(row.data or {})
    domain = data.get("domain")
    if not domain:
        raise BusinessRuleError("agency_profile.data.domain is required first")

    result = await dns_validation.check_all(domain, dkim_selector=payload.dkim_selector)

    mailboxes: list[dict[str, Any]] = list(data.get("sending_mailboxes") or [])
    if not mailboxes:
        # Step 3 can run BEFORE Step 4 (mailbox provisioning) — initialise
        # the placeholder mailbox slot so DNS state has a home.
        mailboxes = [
            {
                "email": "",
                "agent_id": "",
                "purpose": "named_agent_outreach",
                "warmup_status": "pending",
            }
        ]
    mailboxes[0]["dns_records"] = {
        "spf": result.spf.value,
        "dkim": result.dkim.value,
        "dmarc": result.dmarc.value,
        "dkim_selector": result.dkim_selector,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    mailboxes[0]["dns_records_verified"] = result.all_verified
    diff = {"sending_mailboxes": mailboxes}

    service = AgencySetupService(AgencyProfileRepository(session))
    merged = await service.apply_data_patch(row.agency_id, diff)

    if result.all_verified and row.status == "setup_in_progress":
        await service.transition_status(row.agency_id, current=row.status, target="awaiting_dns")
    await session.commit()
    return _envelope(
        {
            "verified": result.all_verified,
            "spf": result.spf.__dict__,
            "dkim": result.dkim.__dict__,
            "dmarc": result.dmarc.__dict__,
            "data": merged,
        }
    )


@router.post("/me/mailbox")
async def provision_mailbox(
    payload: MailboxProvisionRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 4 — provision sending mailbox via Smartlead + persist mailbox id."""
    _require_agency_id_header_warning(request)
    row = await _get_singleton_or_404(session)
    data = dict(row.data or {})
    if not data.get("agents"):
        raise BusinessRuleError("agent must be set before provisioning the mailbox")
    agent = data["agents"][0]
    if agent.get("agent_id") != payload.agent_id:
        raise ValidationError(
            f"agent_id mismatch: payload {payload.agent_id!r} vs profile {agent.get('agent_id')!r}",
            field="agent_id",
        )

    smartlead = SmartleadClient()
    smartlead_response = await smartlead.create_email_account(
        from_name=agent["name"],
        from_email=payload.mailbox_address,
        user_name=payload.smtp_username,
        password=payload.smtp_password,
        smtp_host=payload.smtp_host,
        smtp_port=payload.smtp_port,
        imap_host=payload.imap_host,
        imap_port=payload.imap_port,
        warmup_enabled=True,
        max_email_per_day=payload.daily_send_cap,
    )
    smartlead_id = smartlead_response.get("data", {}).get("id") or smartlead_response.get("id")
    if smartlead_id is None:
        raise BusinessRuleError(
            "Smartlead did not return an email_account id", detail=smartlead_response
        )

    # Preserve any DNS state already attached by Step 3.
    mailboxes = list(data.get("sending_mailboxes") or [{}])
    mailboxes[0].update(
        {
            "email": str(payload.mailbox_address),
            "agent_id": payload.agent_id,
            "purpose": "named_agent_outreach",
            "warmup_status": "pending",
            "smartlead_mailbox_id": str(smartlead_id),
            "daily_send_cap": payload.daily_send_cap,
            "started_warmup_at": datetime.now(UTC).isoformat(),
        }
    )
    diff = {"sending_mailboxes": mailboxes}
    service = AgencySetupService(AgencyProfileRepository(session))
    merged = await service.apply_data_patch(row.agency_id, diff)
    if row.status == "awaiting_dns" and mailboxes[0].get("dns_records_verified"):
        await service.transition_status(row.agency_id, current=row.status, target="warming_up")
    await session.commit()
    return _envelope({"data": merged, "smartlead_mailbox_id": str(smartlead_id)})


@router.patch("/me/signature")
async def patch_signature(
    payload: SignaturePatch,
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 5 — store the default signature template (CAN-SPAM tokens enforced)."""
    _require_agency_id_header_warning(request)
    template = payload.default_signature_template
    required_tokens = ("{agent_name}", "{agency_address}", "{unsubscribe_link}")
    missing = [t for t in required_tokens if t not in template]
    if missing:
        raise ValidationError(
            f"signature template missing required tokens: {missing}",
            field="default_signature_template",
            detail={"missing_tokens": missing},
        )
    row = await _get_singleton_or_404(session)
    diff = {"default_signature_template": template}
    service = AgencySetupService(AgencyProfileRepository(session))
    merged = await service.apply_data_patch(row.agency_id, diff)
    await session.commit()
    return _envelope({"data": merged})


@router.patch("/me/invoice-template")
async def patch_invoice_template(
    payload: InvoiceTemplatePatch,
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 5.5 — write invoice template; server bumps version on material changes."""
    _require_agency_id_header_warning(request)
    row = await _get_singleton_or_404(session)
    current = dict(row.data.get("invoice_template") or {})
    incoming = payload.model_dump(exclude_none=True)
    # First write: seed with the starter template if caller didn't provide.
    if not current and "markdown_source" not in incoming:
        incoming["markdown_source"] = STARTER_TEMPLATE_MARKDOWN
    if "invoice_number_sequence" not in current:
        current["invoice_number_sequence"] = 1
    merged_invoice = materialise_invoice_template_patch(current=current, incoming=incoming)
    diff = {"invoice_template": merged_invoice}
    service = AgencySetupService(AgencyProfileRepository(session))
    merged_full = await service.apply_data_patch(row.agency_id, diff)
    await session.commit()
    return _envelope({"data": merged_full})


@router.patch("/me/commission-defaults")
async def patch_commission_defaults(
    payload: CommissionDefaultsPatch,
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 5.5b — set default commission rate + model."""
    _require_agency_id_header_warning(request)
    row = await _get_singleton_or_404(session)
    diff = {
        "default_commission_rate": payload.default_commission_rate,
        "default_commission_model": payload.default_commission_model,
    }
    service = AgencySetupService(AgencyProfileRepository(session))
    merged = await service.apply_data_patch(row.agency_id, diff)
    await session.commit()
    return _envelope({"data": merged})


@router.post("/me/activate")
async def activate(
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Step 7 — full schema validation + transition to ``active``."""
    _require_agency_id_header_warning(request)
    row = await _get_singleton_or_404(session)
    service = AgencySetupService(AgencyProfileRepository(session))
    new_status = await service.activate(row.agency_id)
    await session.commit()
    return _envelope({"status": new_status, "activated_at": datetime.now(UTC).isoformat()})


# ── Re-exports for tests + main.py ───────────────────────────────────


__all__ = [
    "AgencyCreate",
    "AgencySetupService",
    "AgentPatch",
    "BrandingPatch",
    "CommissionDefaultsPatch",
    "DnsRefreshRequest",
    "InvoiceTemplatePatch",
    "LogoUploadRequest",
    "MailboxProvisionRequest",
    "SignaturePatch",
    "asyncio",
    "router",
    "validate_data_against_schema",
]
