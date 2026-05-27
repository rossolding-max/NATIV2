"""LinkedIn data via RapidAPI's "Real-Time LinkedIn Scraper API".

NOT the official LinkedIn API. The official partner-gated API costs
$10-50k/year and cannot fetch third-party profiles; for v0.1 we use the
RapidAPI gateway endpoint ``linkedin-data-api.p.rapidapi.com``.

Auth: two headers — ``x-rapidapi-key: <RAPIDAPI_KEY>`` plus the gateway-
specific ``x-rapidapi-host: linkedin-data-api.p.rapidapi.com``. The host
is hard-coded because it's specific to this RapidAPI marketplace endpoint,
not a per-deployment value.

If we later adopt more RapidAPI vendors, the gateway boilerplate moves to
``app/vendors/_rapidapi_client.py``.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.errors import IntegrationError
from app.vendors._base import BaseVendorClient
from app.vendors._rate_limiter import check_rate_limit
from app.vendors._retry import async_vendor_retry

_RAPIDAPI_HOST = "linkedin-data-api.p.rapidapi.com"
_RAPIDAPI_BASE_URL = f"https://{_RAPIDAPI_HOST}"


class LinkedInScraperClient(BaseVendorClient):
    """LinkedIn profile + company + activity reader via the RapidAPI gateway.

    Class name says ``Scraper`` deliberately — it's a public-data scraping
    service, not the official LinkedIn API. Future readers should not
    mistake this for partner-gated data.
    """

    vendor_name = "linkedin"

    def __init__(self) -> None:
        if settings.rapidapi_key is None:
            raise IntegrationError(
                "RAPIDAPI_KEY is not configured (LinkedIn data via RapidAPI)",
                detail={"vendor": self.vendor_name},
            )
        self._api_key = settings.rapidapi_key.get_secret_value()

    def _headers(self) -> dict[str, str]:
        return {
            "x-rapidapi-key": self._api_key,
            "x-rapidapi-host": _RAPIDAPI_HOST,
            "Content-Type": "application/json",
        }

    @async_vendor_retry()
    async def get_profile_by_url(self, linkedin_url: str) -> dict[str, Any]:
        """Fetch a person profile by LinkedIn URL.

        Returns the full profile blob; M8 (contact CRM) extracts the
        relevant fields (current_title, company, headline, etc).
        """
        await check_rate_limit(self.vendor_name, "global", max_per_period=30, period_seconds=60)
        response = await self._request(
            "GET",
            f"{_RAPIDAPI_BASE_URL}/",
            endpoint="get_profile_by_url",
            params={"url": linkedin_url},
            headers=self._headers(),
        )
        return response.json()

    @async_vendor_retry()
    async def get_company_by_domain(self, domain: str) -> dict[str, Any]:
        """Fetch a company profile by website domain.

        Used in Phase 3a to map a brand's website to its LinkedIn org page.
        """
        await check_rate_limit(self.vendor_name, "global", max_per_period=30, period_seconds=60)
        response = await self._request(
            "GET",
            f"{_RAPIDAPI_BASE_URL}/get-company-by-domain",
            endpoint="get_company_by_domain",
            params={"domain": domain},
            headers=self._headers(),
        )
        return response.json()

    @async_vendor_retry()
    async def get_recent_posts(self, linkedin_url: str, *, limit: int = 5) -> dict[str, Any]:
        """Fetch a person's recent activity for outreach personalisation.

        Returns up to ``limit`` posts. The RapidAPI endpoint paginates — we
        request the first page only; M8 can extend pagination if needed.
        """
        await check_rate_limit(self.vendor_name, "global", max_per_period=30, period_seconds=60)
        response = await self._request(
            "GET",
            f"{_RAPIDAPI_BASE_URL}/get-profile-posts",
            endpoint="get_recent_posts",
            params={"username": linkedin_url, "limit": limit},
            headers=self._headers(),
        )
        return response.json()
