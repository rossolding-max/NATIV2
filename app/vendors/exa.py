"""Exa client — Phase 2 brand discovery (semantic + keyword search).

Direct httpx to the public Exa REST API (no SDK; the SDK pulls openai as a
transitive dep we don't want). Endpoints used:

- ``POST /search`` — neural / keyword search.
- ``POST /findSimilar`` — given a URL, return similar pages.
- ``POST /contents`` — fetch parsed body content for a list of URLs.

Auth: ``x-api-key`` header. Base URL is configurable via
``EXA_BASE_URL`` (defaults to ``https://api.exa.ai``).
"""

from __future__ import annotations

from typing import Any, Literal

from app.config import settings
from app.errors import IntegrationError
from app.vendors._base import BaseVendorClient
from app.vendors._rate_limiter import check_rate_limit
from app.vendors._retry import async_vendor_retry


class ExaClient(BaseVendorClient):
    """Async client for the Exa search API."""

    vendor_name = "exa"

    def __init__(self) -> None:
        if settings.exa_api_key is None:
            raise IntegrationError(
                "EXA_API_KEY is not configured",
                detail={"vendor": self.vendor_name},
            )
        self._api_key = settings.exa_api_key.get_secret_value()
        self._base_url = str(settings.exa_base_url).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "Content-Type": "application/json",
        }

    @async_vendor_retry()
    async def search(
        self,
        query: str,
        *,
        num_results: int = 10,
        search_type: Literal["neural", "keyword", "auto"] = "auto",
        category: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
        contents: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a search against Exa's neural / keyword index."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=60, period_seconds=60)
        payload: dict[str, Any] = {
            "query": query,
            "numResults": num_results,
            "type": search_type,
        }
        if category is not None:
            payload["category"] = category
        if include_domains:
            payload["includeDomains"] = include_domains
        if exclude_domains:
            payload["excludeDomains"] = exclude_domains
        if contents is not None:
            payload["contents"] = contents

        response = await self._request(
            "POST",
            f"{self._base_url}/search",
            endpoint="search",
            json=payload,
            headers=self._headers(),
        )
        return response.json()

    @async_vendor_retry()
    async def find_similar(
        self,
        url: str,
        *,
        num_results: int = 10,
        contents: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Given a URL, fetch pages Exa deems similar."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=60, period_seconds=60)
        payload: dict[str, Any] = {"url": url, "numResults": num_results}
        if contents is not None:
            payload["contents"] = contents

        response = await self._request(
            "POST",
            f"{self._base_url}/findSimilar",
            endpoint="find_similar",
            json=payload,
            headers=self._headers(),
        )
        return response.json()

    @async_vendor_retry()
    async def get_contents(self, urls: list[str]) -> dict[str, Any]:
        """Fetch parsed text + metadata for one or more URLs."""
        await check_rate_limit(self.vendor_name, "global", max_per_period=60, period_seconds=60)
        response = await self._request(
            "POST",
            f"{self._base_url}/contents",
            endpoint="get_contents",
            json={"urls": urls},
            headers=self._headers(),
        )
        return response.json()
