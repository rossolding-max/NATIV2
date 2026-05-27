"""Meta Graph API client — Phase 4.8 detection + Phase 4.9 KPI capture.

Instagram-Login flow (NOT Facebook-Login): the talent platform onboarding
in M5 directs talents through Instagram's OAuth to grant
``instagram_business_basic`` + ``instagram_business_content_publish`` +
``instagram_business_manage_insights`` scopes.

Tokens are 60-day **long-lived**. Build the refresh check into
construction (M5 stores expires_at; M3 ships the refresh method).

Webhook verification uses ``X-Hub-Signature-256`` with the ``sha256=``
algorithm prefix.

Graph API version pinned to v22.0 — Meta deprecates aggressively; bumping
this is a deliberate ritual.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.config import settings
from app.errors import IntegrationError
from app.vendors._base import BaseVendorClient
from app.vendors._oauth_state import build_authorize_url
from app.vendors._rate_limiter import check_rate_limit
from app.vendors._retry import async_vendor_retry
from app.vendors._webhook_signing import verify_hmac_sha256

_GRAPH_API_VERSION = "v22.0"
_GRAPH_BASE_URL = f"https://graph.facebook.com/{_GRAPH_API_VERSION}"
_INSTAGRAM_AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
_INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"  # noqa: S105 — public OAuth endpoint URL


class MetaGraphClient(BaseVendorClient):
    """Async client for the Meta Graph API (Instagram Business flavour)."""

    vendor_name = "meta_graph"

    def __init__(self) -> None:
        if settings.meta_app_id is None or settings.meta_app_secret is None:
            raise IntegrationError(
                "META_APP_ID and META_APP_SECRET are required",
                detail={"vendor": self.vendor_name},
            )
        self._app_id = settings.meta_app_id
        self._app_secret = settings.meta_app_secret.get_secret_value()

    # ── OAuth ──────────────────────────────────────────────────────────

    def build_authorize_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        scopes: list[str] | None = None,
    ) -> str:
        """Build the Instagram-Login authorize URL.

        Defaults to the M5 scope set; callers can override for testing.
        """
        return build_authorize_url(
            base_url=_INSTAGRAM_AUTHORIZE_URL,
            client_id=self._app_id,
            redirect_uri=redirect_uri,
            scopes=scopes
            or [
                "instagram_business_basic",
                "instagram_business_content_publish",
                "instagram_business_manage_insights",
            ],
            state=state,
        )

    @async_vendor_retry()
    async def exchange_code(self, code: str, redirect_uri: str) -> dict[str, Any]:
        """Exchange a short-lived auth code for a short-lived access token.

        Caller typically follows up with ``refresh_long_lived_token`` to
        upgrade to a 60-day token.
        """
        response = await self._request(
            "POST",
            _INSTAGRAM_TOKEN_URL,
            endpoint="exchange_code",
            data={
                "client_id": self._app_id,
                "client_secret": self._app_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        return response.json()

    @async_vendor_retry()
    async def refresh_long_lived_token(self, access_token: str) -> dict[str, Any]:
        """Refresh a 60-day token. MUST be called before day 60.

        Meta's docs: tokens older than 24h but younger than 60d can be
        refreshed; refreshed tokens get a fresh 60d clock.
        """
        response = await self._request(
            "GET",
            f"{_GRAPH_BASE_URL}/refresh_access_token",
            endpoint="refresh_long_lived_token",
            params={
                "grant_type": "ig_refresh_token",
                "access_token": access_token,
            },
        )
        return response.json()

    # ── Data ───────────────────────────────────────────────────────────

    @async_vendor_retry()
    async def list_media(
        self,
        ig_user_id: str,
        access_token: str,
        *,
        limit: int = 25,
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """List the user's recent media (Reels, posts, carousels)."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=200, period_seconds=3600)
        field_list = fields or [
            "id",
            "media_type",
            "media_url",
            "permalink",
            "timestamp",
            "caption",
        ]
        response = await self._request(
            "GET",
            f"{_GRAPH_BASE_URL}/{ig_user_id}/media",
            endpoint="list_media",
            params={
                "fields": ",".join(field_list),
                "limit": limit,
                "access_token": access_token,
            },
        )
        return response.json()

    @async_vendor_retry()
    async def get_media_insights(
        self,
        media_id: str,
        access_token: str,
        *,
        metrics: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch engagement metrics for a single media item."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=200, period_seconds=3600)
        metric_list = metrics or ["reach", "impressions", "likes", "comments", "saved"]
        response = await self._request(
            "GET",
            f"{_GRAPH_BASE_URL}/{media_id}/insights",
            endpoint="get_media_insights",
            params={"metric": ",".join(metric_list), "access_token": access_token},
        )
        return response.json()

    @async_vendor_retry()
    async def list_stories(self, ig_user_id: str, access_token: str) -> dict[str, Any]:
        """List the user's currently-active Stories (24h ephemeral)."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=200, period_seconds=3600)
        response = await self._request(
            "GET",
            f"{_GRAPH_BASE_URL}/{ig_user_id}/stories",
            endpoint="list_stories",
            params={
                "fields": "id,media_type,media_url,permalink,timestamp",
                "access_token": access_token,
            },
        )
        return response.json()

    # ── Webhook ────────────────────────────────────────────────────────

    def verify_webhook(self, raw_body: bytes, signature_header: str | None) -> bool:
        """Verify an inbound Meta webhook's ``X-Hub-Signature-256`` header.

        The header value is prefixed with ``sha256=``; our helper handles
        the prefix stripping + constant-time compare.
        """
        return verify_hmac_sha256(
            raw_body,
            signature_header,
            self._app_secret,
            algorithm_prefix="sha256=",
        )

    def verify_subscription_challenge(self, mode: str, token: str, challenge: str) -> str | None:
        """Echo back the challenge if the verify-token matches.

        Meta sends GET /webhooks?hub.mode=subscribe&hub.verify_token=...&
        hub.challenge=... once per webhook configuration. We echo
        ``challenge`` only if our META_WEBHOOK_VERIFY_TOKEN matches.
        """
        if settings.meta_webhook_verify_token is None:
            return None
        expected = settings.meta_webhook_verify_token.get_secret_value()
        if mode == "subscribe" and token == expected:
            return challenge
        return None


# Exposed for tests + future code that wants the canonical URL pattern.
def graph_url(path: str) -> str:
    """Return the Graph API URL for ``path`` (slashes normalised)."""
    return f"{_GRAPH_BASE_URL}/{path.lstrip('/')}"


# Re-export so M5 can reuse the qs helper for path-encoded URL composition.
__all__ = ["MetaGraphClient", "graph_url", "urlencode"]
