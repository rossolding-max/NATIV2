"""Smartlead webhook receivers.

Two endpoints, both verify HMAC-SHA256 via the existing helper:

- ``POST /api/v1/webhooks/smartlead/email_event`` — sent / delivered /
  opened / clicked / bounced / unsubscribed.
- ``POST /api/v1/webhooks/smartlead/reply`` — classifies inline and
  triggers the reply-handler pipeline.

Idempotent: dedup on ``(campaign_id, lead_id, event_type, occurred_at)``
keyed in Redis with 24h TTL. Redelivered webhooks (network failures,
Smartlead retry) collapse to a single side-effect.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import APIResponse, make_meta
from app.config import settings
from app.db.session import get_db
from app.errors import AuthorizationError, ValidationError
from app.repositories.brand_contact import BrandContactRepository
from app.repositories.deal import DealRepository
from app.repositories.pitch_enrollment import PitchEnrollmentRepository
from app.utils.logging import get_logger
from app.vendors._webhook_signing import verify_hmac_sha256

log = get_logger(__name__)


router = APIRouter(prefix="/webhooks/smartlead", tags=["webhooks"])

# How long a deduplication key lives (24h is comfortably above any
# Smartlead retry window we've observed).
_DEDUPE_TTL_SECONDS: int = 24 * 60 * 60


def _envelope(data: Any) -> APIResponse[Any]:
    return APIResponse[Any](data=data, meta=make_meta(), errors=[])


async def _verify_signature(request: Request) -> bytes:
    """Read body once, verify HMAC; raise on mismatch."""
    raw = await request.body()
    secret_value = (
        settings.smartlead_webhook_secret.get_secret_value()
        if settings.smartlead_webhook_secret is not None
        else None
    )
    if not secret_value:
        log.warning("smartlead_webhook_no_secret_configured")
        raise AuthorizationError("smartlead webhook secret not configured")
    sig = request.headers.get("X-Smartlead-Signature")
    if not verify_hmac_sha256(raw, sig, secret_value, algorithm_prefix=None):
        raise AuthorizationError(
            "invalid smartlead webhook signature",
            detail={"path": request.url.path},
        )
    return raw


def _dedupe_key(body: dict[str, Any], event_type: str) -> str:
    """Stable dedupe key for ``(campaign_id, lead_id, event_type, occurred_at)``."""
    parts = [
        str(body.get("campaign_id") or ""),
        str(body.get("lead_id") or ""),
        event_type,
        str(body.get("occurred_at") or body.get("event_timestamp") or ""),
    ]
    return (
        "dedup:smartlead:"
        + hashlib.sha1(  # noqa: S324  — dedup key, not security-critical
            "|".join(parts).encode("utf-8")
        ).hexdigest()
    )


async def _seen_before(key: str) -> bool:
    """Set-if-not-exists in Redis. Returns True if the key already existed."""
    try:
        import redis.asyncio as redis

        password = (
            settings.redis_password.get_secret_value()
            if settings.redis_password is not None
            else None
        )
        client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db_cache,
            password=password,
            decode_responses=True,
        )
        try:
            # SET key 1 NX EX 86400 — atomic insert-or-skip.
            result = await client.set(key, "1", nx=True, ex=_DEDUPE_TTL_SECONDS)
            return result is None  # None means "did not set; already existed"
        finally:
            await client.aclose()
    except Exception as exc:
        log.warning("smartlead_dedup_redis_unavailable", error=str(exc))
        return False  # Fail-open — better to process twice than to silently drop.


def _enrollment_id_from(body: dict[str, Any]) -> str | None:
    """Pull the enrollment_id we stashed in lead custom_fields."""
    cf = body.get("custom_fields") or {}
    eid = cf.get("enrollment_id") if isinstance(cf, dict) else None
    if isinstance(eid, str) and eid:
        return eid
    # Fallback: some Smartlead webhooks nest custom fields under "lead".
    lead = body.get("lead") or {}
    if isinstance(lead, dict):
        cf = lead.get("custom_fields") or {}
        eid = cf.get("enrollment_id") if isinstance(cf, dict) else None
        if isinstance(eid, str) and eid:
            return eid
    return None


@router.post("/email_event", status_code=http_status.HTTP_202_ACCEPTED)
async def email_event(
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Handle one engagement event (sent / opened / clicked / bounced / unsubscribed)."""
    raw = await _verify_signature(request)
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid JSON body: {exc!s}") from exc
    if not isinstance(body, dict):
        raise ValidationError("body must be a JSON object")

    event_type = str(body.get("event_type") or "").strip().lower()
    enrollment_id = _enrollment_id_from(body)
    if not enrollment_id:
        log.info("smartlead_email_event_no_enrollment_id", body_keys=list(body.keys()))
        return _envelope({"status": "ignored", "reason": "no_enrollment_id"})

    key = _dedupe_key(body, event_type)
    if await _seen_before(key):
        return _envelope({"status": "duplicate", "enrollment_id": enrollment_id})

    occurred_at = (
        body.get("occurred_at") or body.get("event_timestamp") or datetime.now(UTC).isoformat()
    )
    step_number = int(body.get("seq_number") or body.get("step_number") or 1)
    agency_id = getattr(request.app.state, "agency_id", None)
    if not isinstance(agency_id, UUID):
        agency_id = UUID(int=0)

    repo = PitchEnrollmentRepository(session, agency_id=agency_id)
    contact_repo = BrandContactRepository(session, agency_id=agency_id)

    await repo.upsert_step_event(
        enrollment_id,
        step_number,
        {
            "event_type": event_type,
            "occurred_at": occurred_at,
            "raw": body,
        },
    )

    # Terminal events — kill the enrollment.
    if event_type in {"email_bounced", "bounce"}:
        await repo.set_killed(enrollment_id, kill_reason="bounced")
        # Mark the contact's email as bounced.
        enrollment = await repo.get_by_id(enrollment_id)
        if enrollment is not None:
            await contact_repo.patch_workflow_state(
                enrollment.contact_id,
                {"email": {"verification_status": "bounced"}},
            )
    elif event_type in {"email_unsubscribed", "unsubscribed"}:
        enrollment = await repo.get_by_id(enrollment_id)
        if enrollment is not None:
            await contact_repo.patch_workflow_state(
                enrollment.contact_id,
                {
                    "do_not_contact": True,
                    "do_not_contact_reason": "outreach_unsubscribe",
                    "opt_out_at": occurred_at,
                },
            )
            # Cross-roster kill.
            for active in await repo.find_active_for_contact(enrollment.contact_id):
                await repo.set_killed(active.enrollment_id, kill_reason="unsubscribed")

    await session.commit()
    return _envelope({"status": "processed", "enrollment_id": enrollment_id})


@router.post("/reply", status_code=http_status.HTTP_202_ACCEPTED)
async def reply(
    request: Request,
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Inline-classify a reply and run the side-effect pipeline."""
    raw = await _verify_signature(request)
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"invalid JSON body: {exc!s}") from exc
    if not isinstance(body, dict):
        raise ValidationError("body must be a JSON object")

    enrollment_id = _enrollment_id_from(body)
    if not enrollment_id:
        return _envelope({"status": "ignored", "reason": "no_enrollment_id"})

    occurred_at = (
        body.get("occurred_at") or body.get("event_timestamp") or datetime.now(UTC).isoformat()
    )
    key = _dedupe_key(body, "email_replied")
    if await _seen_before(key):
        return _envelope({"status": "duplicate", "enrollment_id": enrollment_id})

    reply_body = body.get("reply_body") or body.get("body") or body.get("message") or ""
    if not reply_body:
        return _envelope({"status": "ignored", "reason": "empty_reply_body"})

    agency_id = getattr(request.app.state, "agency_id", None)
    if not isinstance(agency_id, UUID):
        agency_id = UUID(int=0)

    from app.services.outreach_reply_handler import handle_reply

    repo = PitchEnrollmentRepository(session, agency_id=agency_id)
    contact_repo = BrandContactRepository(session, agency_id=agency_id)
    deal_repo = DealRepository(session, agency_id=agency_id)

    summary = await handle_reply(
        enrollment_id=enrollment_id,
        reply_body=str(reply_body),
        occurred_at=str(occurred_at),
        agency_id=agency_id,
        enrollment_repo=repo,
        contact_repo=contact_repo,
        deal_repo=deal_repo,
    )
    await session.commit()
    return _envelope(summary)
