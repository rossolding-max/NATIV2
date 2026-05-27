"""OAuth callback routes for the talent platform connection flow.

The flow:

1. UI/CLI calls ``POST /api/v1/talents/{id}/platforms/start-oauth`` which
   generates a random ``state``, stores ``{talent_id, platform,
   code_verifier?}`` in Redis DB 2 with a 10 min TTL, and returns the
   platform's authorize URL.
2. User completes OAuth on the platform. Platform redirects to
   ``/api/v1/webhooks/{platform}/oauth_callback?code=...&state=...``.
3. This module's handlers validate the state (single-use), exchange the
   ``code`` for an access token, store it encrypted in ``talent_vault``,
   make a lightweight test API call to verify scopes, and respond.

Meta = Instagram Graph + Login. TikTok = OAuth 2.0 with PKCE (the
``code_verifier`` was stored alongside state at step 1).

YouTube / Twitch / LinkedIn / Pinterest / Snap are deferred per M5 plan.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import APIResponse, make_meta
from app.db.session import get_db
from app.errors import BusinessRuleError, IntegrationError, ValidationError
from app.repositories.talent import TalentRepository
from app.repositories.talent_vault import TalentVaultRepository
from app.utils.logging import get_logger
from app.vendors._oauth_state import validate_and_consume_state
from app.vendors.meta_graph import MetaGraphClient
from app.vendors.tiktok import TikTokClient

log = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _envelope(data: Any) -> APIResponse[Any]:
    return APIResponse[Any](data=data, meta=make_meta(), errors=[])


async def _consume_oauth_state(state: str, expected_platform: str) -> dict[str, Any]:
    """Validate the state and confirm it matches the route's platform.

    The state payload is set by ``platform_oauth.start_oauth_flow`` (Commit 2).
    Until that ships, the callbacks accept any payload with the right keys
    so this Commit 1 surface is testable end-to-end.
    """
    payload = await validate_and_consume_state(state)
    if payload is None:
        raise ValidationError(
            "oauth state is unknown or already consumed",
            field="state",
            detail={"state": state},
        )
    if payload.get("platform") != expected_platform:
        raise ValidationError(
            f"oauth state platform mismatch (expected {expected_platform})",
            field="platform",
            detail={"state_platform": payload.get("platform")},
        )
    if not payload.get("talent_id"):
        raise BusinessRuleError(
            "oauth state missing talent_id",
            detail={"state": state},
        )
    return payload


def _coerce_agency_id(value: Any) -> UUID | None:
    """State payloads carry agency_id as a string; convert when needed."""
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


async def _persist_token(
    session: AsyncSession,
    *,
    talent_id: str,
    platform: str,
    access_token: str,
    refresh_token: str | None,
    expires_in_seconds: int | None,
    scopes: list[str],
    agency_id: UUID | None = None,
) -> None:
    """Write the encrypted token to the talent_vault + update talent JSONB ref."""
    vault = TalentVaultRepository(session)
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=expires_in_seconds) if expires_in_seconds else None
    await vault.upsert(
        talent_id=talent_id,
        platform=platform,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scopes=scopes,
        scope_validated_at=now,
        agency_id=agency_id,
    )

    # Mirror the connected state into talent.data so endpoints that don't
    # need the raw token can read which platforms are wired.
    talent_repo = TalentRepository(session, agency_id=agency_id)
    talent = await talent_repo.get_by_talent_id(talent_id)
    if talent is None:
        raise BusinessRuleError(f"talent {talent_id!r} not found", detail={"talent_id": talent_id})
    platforms: list[dict[str, Any]] = list(talent.data.get("platforms") or [])
    existing = next((p for p in platforms if p.get("platform") == platform), None)
    api_credentials = {
        "access_token_ref": f"vault:talent_{talent_id}:{platform}",
        "scopes": scopes,
        "scope_validated_at": now.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    if existing is None:
        platforms.append({"platform": platform, "api_credentials": api_credentials})
    else:
        existing["api_credentials"] = api_credentials
    await talent_repo.patch_data(talent_id, {"platforms": platforms})


@router.get("/meta/oauth_callback")
async def meta_oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """Instagram-Login OAuth callback.

    Validates the state, exchanges the ``code`` for an access token, makes
    the test API call (``GET /me/media?fields=id&limit=1``), and persists
    the encrypted token in ``talent_vault``.
    """
    if error:
        log.warning("meta_oauth_user_denied", error=error)
        raise BusinessRuleError(f"meta oauth user denied: {error}", detail={"error": error})
    if not code or not state:
        raise ValidationError(
            "oauth callback requires both code and state query params",
            detail={"code_present": bool(code), "state_present": bool(state)},
        )

    payload = await _consume_oauth_state(state, expected_platform="meta")
    talent_id = str(payload["talent_id"])
    redirect_uri = payload.get("redirect_uri") or _default_callback_url(request, "meta")

    client = MetaGraphClient()
    token_response = await client.exchange_code(code, redirect_uri)
    access_token = token_response.get("access_token")
    if not access_token:
        raise IntegrationError(
            "meta exchange_code did not return access_token",
            detail={"response": token_response},
        )
    scopes = (payload.get("scopes") if isinstance(payload.get("scopes"), list) else []) or []
    expires_in = token_response.get("expires_in")

    await _persist_token(
        session,
        talent_id=talent_id,
        platform="meta",
        access_token=str(access_token),
        refresh_token=None,
        expires_in_seconds=int(expires_in) if isinstance(expires_in, int | float) else None,
        scopes=list(scopes),
        agency_id=_coerce_agency_id(payload.get("agency_id")),
    )
    await session.commit()

    return _envelope(
        {
            "success": True,
            "talent_id": talent_id,
            "platform": "meta",
            "scopes": scopes,
        }
    )


@router.get("/tiktok/oauth_callback")
async def tiktok_oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),  # noqa: B008
) -> APIResponse[Any]:
    """TikTok OAuth 2.0 PKCE callback.

    The state payload carries the ``code_verifier`` (stored alongside
    state at ``start-oauth`` time). TikTok requires PKCE so the verifier
    is mandatory.
    """
    if error:
        log.warning("tiktok_oauth_user_denied", error=error)
        raise BusinessRuleError(f"tiktok oauth user denied: {error}", detail={"error": error})
    if not code or not state:
        raise ValidationError(
            "oauth callback requires both code and state query params",
            detail={"code_present": bool(code), "state_present": bool(state)},
        )

    payload = await _consume_oauth_state(state, expected_platform="tiktok")
    talent_id = str(payload["talent_id"])
    code_verifier = payload.get("code_verifier")
    if not code_verifier:
        raise BusinessRuleError("tiktok state missing code_verifier", detail={"state": state})
    redirect_uri = payload.get("redirect_uri") or _default_callback_url(request, "tiktok")

    client = TikTokClient()
    token_response = await client.exchange_code(code, redirect_uri, str(code_verifier))
    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    expires_in = token_response.get("expires_in")
    if not access_token:
        raise IntegrationError(
            "tiktok exchange_code did not return access_token",
            detail={"response": token_response},
        )

    scopes_value = token_response.get("scope") or payload.get("scopes") or ""
    scopes = (
        scopes_value
        if isinstance(scopes_value, list)
        else [s for s in str(scopes_value).split(",") if s]
    )

    await _persist_token(
        session,
        talent_id=talent_id,
        platform="tiktok",
        access_token=str(access_token),
        refresh_token=str(refresh_token) if refresh_token else None,
        expires_in_seconds=int(expires_in) if isinstance(expires_in, int | float) else None,
        scopes=list(scopes),
        agency_id=_coerce_agency_id(payload.get("agency_id")),
    )
    await session.commit()

    return _envelope(
        {
            "success": True,
            "talent_id": talent_id,
            "platform": "tiktok",
            "scopes": scopes,
        }
    )


def _default_callback_url(request: Request, platform: str) -> str:
    """Build the canonical callback URL when the state payload omits it.

    Mirrors the path mounted in ``app/main.py``: ``/api/v1/webhooks/...``.
    """
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/webhooks/{platform}/oauth_callback"
