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

    # ── Phase 0 email-account / mailbox warmup ───────────────────────────
    #
    # Smartlead endpoints (verified against
    # https://api.smartlead.ai/reference/create-an-email-account +
    # https://api.smartlead.ai/reference/addupdate-warmup-to-email-account):
    #
    #   POST /email-accounts/save                — create
    #   GET  /email-accounts/{id}/               — fetch
    #   POST /email-accounts/{id}/warmup         — enable/configure warmup
    #   GET  /email-accounts/{id}/warmup-stats   — last-7-day deliverability
    #
    # Smartlead does NOT expose a DNS-verification API; SPF/DKIM/DMARC checks
    # are done directly via dnspython in app/services/dns_validation.py.

    @async_vendor_retry()
    async def create_email_account(
        self,
        *,
        from_name: str,
        from_email: str,
        user_name: str,
        password: str,
        smtp_host: str,
        smtp_port: int,
        imap_host: str,
        imap_port: int,
        warmup_enabled: bool = True,
        max_email_per_day: int | None = None,
        signature: str | None = None,
        provider_type: str = "SMTP",
    ) -> dict[str, Any]:
        """Provision a sending mailbox in Smartlead. Returns ``id`` + connectivity flags."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=30, period_seconds=60)
        payload: dict[str, Any] = {
            "from_name": from_name,
            "from_email": from_email,
            "user_name": user_name,
            "password": password,
            "smtp_host": smtp_host,
            "smtp_port": smtp_port,
            "imap_host": imap_host,
            "imap_port": imap_port,
            "warmup_enabled": warmup_enabled,
            "type": provider_type,
        }
        if max_email_per_day is not None:
            payload["max_email_per_day"] = max_email_per_day
        if signature is not None:
            payload["signature"] = signature
        response = await self._request(
            "POST",
            self._url("/email-accounts/save"),
            endpoint="create_email_account",
            params=self._auth_params(),
            json=payload,
        )
        return response.json()

    @async_vendor_retry()
    async def get_email_account(self, email_account_id: str | int) -> dict[str, Any]:
        """Fetch a single email account incl. warmup state."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=120, period_seconds=60)
        response = await self._request(
            "GET",
            self._url(f"/email-accounts/{email_account_id}/"),
            endpoint="get_email_account",
            params=self._auth_params(),
        )
        return response.json()

    @async_vendor_retry()
    async def update_warmup_settings(
        self,
        email_account_id: str | int,
        *,
        warmup_enabled: bool,
        total_warmup_per_day: int = 20,
        daily_rampup: int = 2,
        reply_rate_percentage: int = 30,
    ) -> dict[str, Any]:
        """Enable + configure warmup on an existing email account."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=30, period_seconds=60)
        response = await self._request(
            "POST",
            self._url(f"/email-accounts/{email_account_id}/warmup"),
            endpoint="update_warmup_settings",
            params=self._auth_params(),
            json={
                "warmup_enabled": warmup_enabled,
                "total_warmup_per_day": total_warmup_per_day,
                "daily_rampup": daily_rampup,
                "reply_rate_percentage": reply_rate_percentage,
            },
        )
        return response.json()

    @async_vendor_retry()
    async def get_warmup_stats(self, email_account_id: str | int) -> dict[str, Any]:
        """Return last-7-day warmup deliverability (sent / inbox / spam)."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=60, period_seconds=60)
        response = await self._request(
            "GET",
            self._url(f"/email-accounts/{email_account_id}/warmup-stats"),
            endpoint="get_warmup_stats",
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
