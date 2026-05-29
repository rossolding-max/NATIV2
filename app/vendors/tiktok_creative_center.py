"""TikTok Creative Center client — Search 17 (paid social ad signal).

v1 of the M7.2 paid-social-signal pipeline. Hits TikTok's unofficial
public JSON endpoint that backs the Creative Center web UI
(``https://ads.tiktok.com/creative_radar_api/v1/top_ads/v2/list``).

Why "unofficial": the JSON endpoint is what the React frontend at
``ads.tiktok.com/business/creativecenter/`` calls. It's not formally
documented as a public API. We rate-limit aggressively + identify
ourselves via User-Agent, AND we fail soft (return empty list on any
non-200 / unexpected-shape response) so a broken endpoint never crashes
a discovery run.

When TikTok Marketing API access is granted (waitlisted in v1), this
module gets swapped for ``app/vendors/tiktok_ads.py`` with the same
public interface — Search 17 caller doesn't change.
"""

from __future__ import annotations

from typing import Any

from app.utils.logging import get_logger
from app.vendors._base import BaseVendorClient
from app.vendors._rate_limiter import check_rate_limit
from app.vendors._retry import async_vendor_retry

log = get_logger(__name__)


class TikTokCreativeCenterClient(BaseVendorClient):
    """v1 scraper for the public Creative Center JSON endpoint.

    Identifies as ``NATIV2/0.1`` so the agency's traffic is attributable.
    Rate-limit defaults are conservative — 1 req/3s per the M7.2 spec — to
    be a good neighbour while TikTok's official API access is pending.
    """

    vendor_name = "tiktok_creative_center"

    def __init__(self) -> None:
        self._base_url = "https://ads.tiktok.com/creative_radar_api/v1"
        self._user_agent = "NATIV2/0.1 (creator agency research)"

    @async_vendor_retry()
    async def fetch_top_ads(
        self,
        *,
        industry: str | None = None,
        region: str = "US",
        period_days: int = 30,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Fetch the Creative Center's top-ads list for a region.

        ``industry`` is a free-text tag that TikTok matches against their
        own industry taxonomy (we don't try to map our industry_ids to
        theirs in v1 — we pass them raw and let TikTok ignore unknown
        values).

        Returns the raw JSON shape ``{"data": [...ads], "code": int, ...}``.
        On any non-200 response OR a response that doesn't have ``"data"``
        as a list, returns ``{"data": []}`` so callers degrade gracefully.
        """
        await check_rate_limit(
            self.vendor_name, "global", max_per_period=20, period_seconds=60
        )
        params: dict[str, Any] = {
            "period": period_days,
            "region": region,
            "limit": limit,
            "page": 1,
        }
        if industry:
            params["industry"] = industry

        try:
            response = await self._request(
                "GET",
                f"{self._base_url}/top_ads/v2/list",
                endpoint="top_ads_list",
                params=params,
                headers={"User-Agent": self._user_agent},
            )
        except Exception as exc:
            log.warning(
                "tiktok_cc_fetch_failed_softfallback",
                error=str(exc),
                industry=industry,
                region=region,
            )
            return {"data": []}

        try:
            body = response.json()
        except Exception as exc:
            log.warning(
                "tiktok_cc_response_not_json",
                error=str(exc),
                status=response.status_code,
            )
            return {"data": []}

        if not isinstance(body, dict) or not isinstance(body.get("data"), list):
            log.warning(
                "tiktok_cc_unexpected_shape",
                keys=list(body.keys()) if isinstance(body, dict) else None,
            )
            return {"data": []}
        return body

    async def count_active_advertisers_per_industry(
        self,
        *,
        industries: list[str],
        region: str = "US",
        period_days: int = 30,
        per_industry_limit: int = 50,
    ) -> dict[str, dict[str, Any]]:
        """Aggregate top-ads across industries into ``{brand_name -> {industries, ad_count, ...}}``.

        For each industry we make a single request. Brands that surface
        across multiple industries get their ``industries`` list extended
        and their ``ad_count`` summed.
        """
        aggregate: dict[str, dict[str, Any]] = {}
        for industry in industries:
            raw = await self.fetch_top_ads(
                industry=industry,
                region=region,
                period_days=period_days,
                limit=per_industry_limit,
            )
            for ad in raw.get("data") or []:
                if not isinstance(ad, dict):
                    continue
                brand_name = (ad.get("brand_name") or ad.get("advertiser") or "").strip()
                if not brand_name:
                    continue
                entry = aggregate.setdefault(
                    brand_name,
                    {
                        "industries": [],
                        "ad_count": 0,
                        "regions": [region],
                        "sample_video_url": ad.get("video_url"),
                    },
                )
                entry["ad_count"] += 1
                if industry not in entry["industries"]:
                    entry["industries"].append(industry)
        return aggregate


# Defaults exported here so config.py and tests can reference them
# without import cycles.
DEFAULT_TIKTOK_REGION: str = "US"
DEFAULT_TIKTOK_PERIOD_DAYS: int = 30
DEFAULT_TIKTOK_PER_INDUSTRY_LIMIT: int = 50

__all__ = (
    "DEFAULT_TIKTOK_PERIOD_DAYS",
    "DEFAULT_TIKTOK_PER_INDUSTRY_LIMIT",
    "DEFAULT_TIKTOK_REGION",
    "TikTokCreativeCenterClient",
)
