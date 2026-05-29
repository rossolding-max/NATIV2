"""Meta Ad Library client — Search 17 (paid social ad signal).

Wraps the public Meta Ad Library REST endpoint
(``https://graph.facebook.com/v22.0/ads_archive``). Free + public; auth via
a Meta app access token (``settings.meta_ads_api_token``). Rate limits per
Meta docs: 200 req/hr on the free tier.

This is a v1 client — count-based signal only (number of active ads per
advertiser page, filtered to a region + last-30-day window). v2 will
swap to a paid spend-intelligence vendor for estimated $ values per
Pathmatics / SensorTower / AdBeat.
"""

from __future__ import annotations

from typing import Any, Literal

from app.config import settings
from app.errors import IntegrationError
from app.vendors._base import BaseVendorClient
from app.vendors._rate_limiter import check_rate_limit
from app.vendors._retry import async_vendor_retry


class MetaAdsClient(BaseVendorClient):
    """Async client for Meta's Ad Library API (read-only public).

    Per the Meta docs, the only required auth is an app access token; we
    pass it as the ``access_token`` query parameter (Meta's convention).
    The client is otherwise unopinionated about page-name normalisation —
    that happens at the search-layer (M7.2's search_17).
    """

    vendor_name = "meta_ads"

    def __init__(self) -> None:
        if settings.meta_ads_api_token is None:
            raise IntegrationError(
                "META_ADS_API_TOKEN is not configured",
                detail={"vendor": self.vendor_name},
            )
        self._access_token = settings.meta_ads_api_token.get_secret_value()
        self._base_url = "https://graph.facebook.com/v22.0"

    @async_vendor_retry()
    async def search_ads(
        self,
        *,
        search_terms: str,
        countries: list[str],
        ad_active_status: Literal["ACTIVE", "INACTIVE", "ALL"] = "ACTIVE",
        ad_type: Literal[
            "ALL", "POLITICAL_AND_ISSUE_ADS", "HOUSING_ADS", "EMPLOYMENT_ADS"
        ] = "ALL",
        limit: int = 100,
        ad_delivery_date_min: str | None = None,
    ) -> dict[str, Any]:
        """Fetch active ads matching ``search_terms`` in the given countries.

        Returns the raw Meta response shape: ``{"data": [...ads], "paging": {...}}``.
        Each ad carries ``page_name`` + ``page_id`` + ``ad_creative_bodies`` +
        ``ad_creation_time`` etc.

        Args:
            search_terms: Free-text query Meta matches against ad copy +
                advertiser name.
            countries: ISO 3166-1 alpha-2 codes. M7.2 default = ``["US", "UK", "AU"]``.
            ad_active_status: ``"ACTIVE"`` filters to ads currently running.
            ad_type: ``"ALL"`` returns everything; we strip
                ``POLITICAL_AND_ISSUE_ADS`` post-hoc (Meta won't OR them).
            limit: Page size. Meta caps at 1000; we default to 100 for
                budget safety.
            ad_delivery_date_min: ISO date (``"2026-04-29"``) to bound the
                lookback window — Meta returns ads that have been delivered
                AT ANY POINT since this date.
        """
        await check_rate_limit(
            self.vendor_name, "global", max_per_period=200, period_seconds=3600
        )
        fields = (
            "id,page_name,page_id,ad_snapshot_url,ad_creation_time,"
            "ad_delivery_start_time,ad_delivery_stop_time,languages"
        )
        params: dict[str, Any] = {
            "access_token": self._access_token,
            "search_terms": search_terms,
            "ad_reached_countries": ",".join(countries),
            "ad_active_status": ad_active_status,
            "ad_type": ad_type,
            "fields": fields,
            "limit": limit,
        }
        if ad_delivery_date_min:
            params["ad_delivery_date_min"] = ad_delivery_date_min

        response = await self._request(
            "GET",
            f"{self._base_url}/ads_archive",
            endpoint="ads_archive_search",
            params=params,
        )
        return response.json()

    async def count_active_ads_per_advertiser(
        self,
        *,
        search_terms: str,
        countries: list[str],
        days_back: int = 30,
        max_results: int = 500,
    ) -> dict[str, dict[str, Any]]:
        """Aggregate ``search_ads`` results into ``{page_name -> {page_id, ad_count, ...}}``.

        Handles pagination up to ``max_results`` ads. Filters out ads with
        no ``page_name`` (junk records). Drops Political ads even though
        we request ``ad_type=ALL`` — Meta sometimes mixes them in.

        Returns a dict keyed by page_name for easy merging with the TikTok
        client's output downstream.
        """
        from datetime import UTC, datetime, timedelta

        date_min = (datetime.now(UTC) - timedelta(days=days_back)).date().isoformat()
        aggregate: dict[str, dict[str, Any]] = {}
        collected = 0

        # M7.2 v1 does not follow pagination cursors — one page (up to ``limit``
        # ads) is enough for the count signal. Pagination defers to M7.3 if
        # higher-volume industries need it.
        raw = await self.search_ads(
            search_terms=search_terms,
            countries=countries,
            limit=min(max_results, 100),
            ad_delivery_date_min=date_min,
        )

        for ad in raw.get("data") or []:
            if not isinstance(ad, dict):
                continue
            page_name = (ad.get("page_name") or "").strip()
            if not page_name:
                continue
            collected += 1
            if collected > max_results:
                break
            entry = aggregate.setdefault(
                page_name,
                {
                    "page_id": ad.get("page_id"),
                    "ad_count": 0,
                    "sample_ad_snapshot_url": ad.get("ad_snapshot_url"),
                    "languages": [],
                },
            )
            entry["ad_count"] += 1
            for lang in ad.get("languages") or []:
                if lang not in entry["languages"]:
                    entry["languages"].append(lang)
        return aggregate
