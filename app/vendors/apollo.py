"""Apollo.io client — Phase 3a contact enrichment.

Endpoints used:

- ``POST /v1/mixed_people/search`` — multi-condition people search.
- ``POST /v1/people/match`` — single-person enrich (by LinkedIn URL,
  email, or name + domain).
- ``POST /v1/organizations/enrich`` — company enrich by domain.

Auth: ``X-Api-Key`` header (Apollo's exact casing). Apollo returns
``X-RateLimit-Remaining`` + ``X-RateLimit-Reset`` headers; v0.1 leaves
header-based pre-emption to Apollo's own 429 response — our token bucket
just keeps us well under the documented per-minute cap.
"""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.errors import IntegrationError
from app.vendors._base import BaseVendorClient
from app.vendors._rate_limiter import check_rate_limit
from app.vendors._retry import async_vendor_retry

_APOLLO_BASE_URL = "https://api.apollo.io"


class ApolloClient(BaseVendorClient):
    """Async client for the Apollo.io API."""

    vendor_name = "apollo"

    def __init__(self) -> None:
        if settings.apollo_api_key is None:
            raise IntegrationError(
                "APOLLO_API_KEY is not configured",
                detail={"vendor": self.vendor_name},
            )
        self._api_key = settings.apollo_api_key.get_secret_value()

    def _headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self._api_key,
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
        }

    @async_vendor_retry()
    async def search_people(
        self,
        *,
        domain: str | None = None,
        organization_ids: list[str] | None = None,
        titles: list[str] | None = None,
        seniorities: list[str] | None = None,
        page: int = 1,
        per_page: int = 25,
    ) -> dict[str, Any]:
        """Multi-condition people search.

        Use ``domain`` for the common "find marketing decision-makers at
        example.com" workflow. ``titles`` and ``seniorities`` narrow further.
        """
        await check_rate_limit(self.vendor_name, "global", max_per_period=60, period_seconds=60)
        payload: dict[str, Any] = {"page": page, "per_page": per_page}
        if domain is not None:
            payload["q_organization_domains"] = [domain]
        if organization_ids:
            payload["organization_ids"] = organization_ids
        if titles:
            payload["person_titles"] = titles
        if seniorities:
            payload["person_seniorities"] = seniorities

        response = await self._request(
            "POST",
            f"{_APOLLO_BASE_URL}/v1/mixed_people/search",
            endpoint="search_people",
            json=payload,
            headers=self._headers(),
        )
        return response.json()

    @async_vendor_retry()
    async def match_person(
        self,
        *,
        linkedin_url: str | None = None,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        organization_domain: str | None = None,
    ) -> dict[str, Any]:
        """Enrich a single person.

        At least one of (``linkedin_url``, ``email``, full name + domain)
        must be supplied; Apollo decides which signal to use.
        """
        if (
            linkedin_url is None
            and email is None
            and not (first_name and last_name and organization_domain)
        ):
            raise IntegrationError(
                "match_person requires linkedin_url, email, or (name + domain)",
                detail={"vendor": self.vendor_name, "endpoint": "match_person"},
            )

        await check_rate_limit(self.vendor_name, "global", max_per_period=60, period_seconds=60)
        payload: dict[str, Any] = {}
        if linkedin_url is not None:
            payload["linkedin_url"] = linkedin_url
        if email is not None:
            payload["email"] = email
        if first_name is not None:
            payload["first_name"] = first_name
        if last_name is not None:
            payload["last_name"] = last_name
        if organization_domain is not None:
            payload["organization_name"] = organization_domain

        response = await self._request(
            "POST",
            f"{_APOLLO_BASE_URL}/v1/people/match",
            endpoint="match_person",
            json=payload,
            headers=self._headers(),
        )
        return response.json()

    @async_vendor_retry()
    async def enrich_organization(self, domain: str) -> dict[str, Any]:
        """Enrich a company by domain."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=60, period_seconds=60)
        response = await self._request(
            "POST",
            f"{_APOLLO_BASE_URL}/v1/organizations/enrich",
            endpoint="enrich_organization",
            json={"domain": domain},
            headers=self._headers(),
        )
        return response.json()
