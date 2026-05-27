"""TikTok Display API client — Phase 4.8 detection + Phase 4.9 KPI capture.

TikTok requires PKCE on the authorize step:

- Generate a random ``code_verifier`` (43-128 chars, URL-safe).
- Derive ``code_challenge`` = SHA256(verifier) → base64-url-no-pad.
- Send the challenge on /v2/auth/authorize; store the verifier alongside
  the OAuth state in Redis (via ``_oauth_state.store_state``).
- On callback, retrieve the verifier and pass it to /v2/oauth/token along
  with the auth code.

Tokens: 24h access + 365d refresh. Refresh aggressively (every call should
check expires_at; M5 will own the timer).

Rate limit: ~100 calls/day per user — TIGHT. The shared token bucket
defends; cron cadences for detection have to fit inside this budget.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any

from app.config import settings
from app.errors import IntegrationError
from app.vendors._base import BaseVendorClient
from app.vendors._oauth_state import build_authorize_url
from app.vendors._rate_limiter import check_rate_limit
from app.vendors._retry import async_vendor_retry

_TIKTOK_AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"
_TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"  # noqa: S105 — public OAuth endpoint URL
_TIKTOK_API_BASE_URL = "https://open.tiktokapis.com/v2"


def generate_pkce_pair() -> tuple[str, str]:
    """Generate a (code_verifier, code_challenge) pair for the PKCE flow.

    - verifier: 96 random URL-safe chars (≈128 bytes of entropy).
    - challenge: ``base64url-no-pad(SHA256(verifier))``.
    """
    verifier = secrets.token_urlsafe(96)
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


class TikTokClient(BaseVendorClient):
    """Async client for the TikTok Display API."""

    vendor_name = "tiktok"

    def __init__(self) -> None:
        if settings.tiktok_client_key is None or settings.tiktok_client_secret is None:
            raise IntegrationError(
                "TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET are required",
                detail={"vendor": self.vendor_name},
            )
        self._client_key = settings.tiktok_client_key
        self._client_secret = settings.tiktok_client_secret.get_secret_value()

    # ── OAuth ──────────────────────────────────────────────────────────

    def build_authorize_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        scopes: list[str] | None = None,
    ) -> str:
        """Build the TikTok OAuth authorize URL with PKCE.

        Caller MUST first call ``generate_pkce_pair()`` and persist the
        verifier via ``_oauth_state.store_state`` keyed by ``state``.
        """
        return build_authorize_url(
            base_url=_TIKTOK_AUTHORIZE_URL,
            client_id=self._client_key,
            redirect_uri=redirect_uri,
            scopes=scopes or ["user.info.basic", "video.list"],
            state=state,
            extra={
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            },
        )

    @async_vendor_retry()
    async def exchange_code(
        self, code: str, redirect_uri: str, code_verifier: str
    ) -> dict[str, Any]:
        """Exchange an auth code for an access + refresh token pair.

        ``code_verifier`` is the value persisted alongside the OAuth state.
        TikTok verifies SHA256(verifier) == the challenge sent on authorize.
        """
        response = await self._request(
            "POST",
            _TIKTOK_TOKEN_URL,
            endpoint="exchange_code",
            data={
                "client_key": self._client_key,
                "client_secret": self._client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return response.json()

    @async_vendor_retry()
    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Refresh a TikTok access token using a stored refresh token."""
        response = await self._request(
            "POST",
            _TIKTOK_TOKEN_URL,
            endpoint="refresh_token",
            data={
                "client_key": self._client_key,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        return response.json()

    # ── Data ───────────────────────────────────────────────────────────

    @async_vendor_retry()
    async def list_videos(
        self,
        access_token: str,
        *,
        cursor: int = 0,
        max_count: int = 20,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """List the user's videos.

        Rate limit is ~100 calls/day per user — the shared bucket throttles
        well under that for safety.
        """
        await check_rate_limit(self.vendor_name, "global", max_per_period=4, period_seconds=3600)
        field_list = fields or [
            "id",
            "title",
            "cover_image_url",
            "share_url",
            "video_description",
            "create_time",
        ]
        response = await self._request(
            "POST",
            f"{_TIKTOK_API_BASE_URL}/video/list/",
            endpoint="list_videos",
            params={"fields": ",".join(field_list)},
            json={"cursor": cursor, "max_count": max_count},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        return response.json()

    @async_vendor_retry()
    async def query_video(
        self,
        access_token: str,
        video_ids: list[str],
        *,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch detail (including stats) for one or more videos by id."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=4, period_seconds=3600)
        field_list = fields or [
            "id",
            "view_count",
            "like_count",
            "comment_count",
            "share_count",
        ]
        response = await self._request(
            "POST",
            f"{_TIKTOK_API_BASE_URL}/video/query/",
            endpoint="query_video",
            params={"fields": ",".join(field_list)},
            json={"filters": {"video_ids": video_ids}},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
        )
        return response.json()

    @async_vendor_retry()
    async def get_user_info(self, access_token: str) -> dict[str, Any]:
        """Fetch basic profile info for the authorised user."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=12, period_seconds=3600)
        response = await self._request(
            "GET",
            f"{_TIKTOK_API_BASE_URL}/user/info/",
            endpoint="get_user_info",
            params={"fields": "open_id,union_id,avatar_url,display_name,username"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        return response.json()
