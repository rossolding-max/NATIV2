"""Smartlead client — Phase 3b outreach (campaigns, leads, sequences, webhooks).

Smartlead auth quirk: the API key goes on the QUERY STRING (``?api_key=...``),
not in an Authorization header. Don't copy the header-auth pattern from other
vendors here.

Webhook signature: ``X-Smartlead-Signature`` = HMAC-SHA256(raw_body, secret),
hex-encoded, NO algorithm prefix.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.errors import IntegrationError
from app.vendors._base import BaseVendorClient
from app.vendors._rate_limiter import check_rate_limit
from app.vendors._retry import async_vendor_retry
from app.vendors._webhook_signing import verify_hmac_sha256


class SmartleadClient(BaseVendorClient):
    """Async client for the Smartlead API.

    Methods cover the Phase 0 (mailbox warmup) + Phase 3b (campaign/lead/
    sequence) needs. Webhook helpers verify Smartlead's HMAC and parse
    engagement events.
    """

    vendor_name = "smartlead"

    def __init__(self) -> None:
        if settings.smartlead_api_key is None:
            raise IntegrationError(
                "SMARTLEAD_API_KEY is not configured",
                detail={"vendor": self.vendor_name},
            )
        self._api_key = settings.smartlead_api_key.get_secret_value()
        self._base_url = str(settings.smartlead_base_url).rstrip("/")

    def _url(self, path: str) -> str:
        return f"{self._base_url}/{path.lstrip('/')}"

    def _auth_params(self, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"api_key": self._api_key}
        if extra is not None:
            params.update(extra)
        return params

    @async_vendor_retry()
    async def create_campaign(self, name: str, client_id: str | None = None) -> dict[str, Any]:
        """Create a new outreach campaign."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=60, period_seconds=60)
        payload: dict[str, Any] = {"name": name}
        if client_id is not None:
            payload["client_id"] = client_id
        response = await self._request(
            "POST",
            self._url("/campaigns/create"),
            endpoint="create_campaign",
            params=self._auth_params(),
            json=payload,
        )
        return response.json()

    @async_vendor_retry()
    async def add_leads(self, campaign_id: str, leads: list[dict[str, Any]]) -> dict[str, Any]:
        """Add leads (recipients) to a campaign.

        Each lead dict mirrors Smartlead's lead shape: at minimum
        ``email`` + ``first_name``; ``last_name``, ``company_name``, and
        ``custom_fields`` are optional.
        """
        await check_rate_limit(self.vendor_name, "global", max_per_period=60, period_seconds=60)
        response = await self._request(
            "POST",
            self._url(f"/campaigns/{campaign_id}/leads"),
            endpoint="add_leads",
            params=self._auth_params(),
            json={"lead_list": leads},
        )
        return response.json()

    @async_vendor_retry()
    async def add_sequence(
        self, campaign_id: str, sequences: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Attach the email sequence template to a campaign."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=60, period_seconds=60)
        response = await self._request(
            "POST",
            self._url(f"/campaigns/{campaign_id}/sequences"),
            endpoint="add_sequence",
            params=self._auth_params(),
            json={"sequences": sequences},
        )
        return response.json()

    @async_vendor_retry()
    async def pause_campaign(self, campaign_id: str) -> dict[str, Any]:
        """Pause a running campaign (no longer schedules new sends)."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=60, period_seconds=60)
        response = await self._request(
            "POST",
            self._url(f"/campaigns/{campaign_id}/status"),
            endpoint="pause_campaign",
            params=self._auth_params(),
            json={"status": "PAUSED"},
        )
        return response.json()

    @async_vendor_retry()
    async def get_campaign_status(self, campaign_id: str) -> dict[str, Any]:
        """Return the campaign status + summary metrics."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=120, period_seconds=60)
        response = await self._request(
            "GET",
            self._url(f"/campaigns/{campaign_id}"),
            endpoint="get_campaign_status",
            params=self._auth_params(),
        )
        return response.json()

    # ── Webhook helpers ──────────────────────────────────────────────────

    def verify_webhook(self, raw_body: bytes, signature_header: str | None) -> bool:
        """Verify an inbound webhook's ``X-Smartlead-Signature`` header.

        Returns ``True`` iff the secret-signed HMAC of the raw body matches
        the header value. ``False`` for any malformed input. Callers MUST
        reject (HTTP 401) on ``False``.
        """
        if settings.smartlead_webhook_secret is None:
            return False
        return verify_hmac_sha256(
            raw_body,
            signature_header,
            settings.smartlead_webhook_secret.get_secret_value(),
        )

    @staticmethod
    def parse_engagement_event(body: dict[str, Any]) -> dict[str, Any]:
        """Normalise a Smartlead engagement-event body into our internal shape.

        Pulls out the high-value fields M9 (outreach) cares about. Unknown
        event types pass through unchanged; M9 decides whether to act on them.
        """
        return {
            "event_type": body.get("event_type"),
            "campaign_id": body.get("campaign_id"),
            "lead_id": body.get("lead_id"),
            "lead_email": body.get("lead_email"),
            "occurred_at": body.get("occurred_at"),
            "raw": body,
        }
