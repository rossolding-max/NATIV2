"""Integration tests for ``TikTokCreativeCenterClient`` (respx-mocked)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx

from app.vendors import _http_client


@pytest.fixture(autouse=True)
def _vendor_settings() -> Any:  # pyright: ignore[reportUnusedFunction]
    _http_client.reset_client_for_tests()
    yield
    _http_client.reset_client_for_tests()


@pytest.fixture
def _rate_limit_ok() -> Any:  # pyright: ignore[reportUnusedFunction]
    async def _noop(
        _vendor: str, _bucket: str, *, max_per_period: int, period_seconds: int
    ) -> None:
        return None

    with patch("app.vendors.tiktok_creative_center.check_rate_limit", _noop):
        yield


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__tiktok_cc__top_ads_happy_path() -> None:
    from app.vendors.tiktok_creative_center import TikTokCreativeCenterClient

    route = respx.get("https://ads.tiktok.com/creative_radar_api/v1/top_ads/v2/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"brand_name": "Alo Yoga", "video_url": "https://x"},
                    {"advertiser": "Gymshark", "video_url": "https://y"},
                ],
                "code": 0,
            },
        )
    )

    client = TikTokCreativeCenterClient()
    out = await client.fetch_top_ads(industry="activewear", region="US")
    assert len(out["data"]) == 2
    req = route.calls[0].request
    assert "industry=activewear" in str(req.url)
    assert "region=US" in str(req.url)
    # We identify ourselves with a custom user-agent.
    assert "NATIV2" in req.headers.get("user-agent", "")


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__tiktok_cc__non_200_softfallback() -> None:
    """A 4xx/5xx response degrades to {data: []} rather than raising."""
    from app.vendors.tiktok_creative_center import TikTokCreativeCenterClient

    respx.get("https://ads.tiktok.com/creative_radar_api/v1/top_ads/v2/list").mock(
        return_value=httpx.Response(503, text="upstream down")
    )

    client = TikTokCreativeCenterClient()
    out = await client.fetch_top_ads(industry="activewear")
    assert out == {"data": []}


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__tiktok_cc__unexpected_shape_softfallback() -> None:
    """A 200 with the wrong JSON shape also degrades to {data: []}."""
    from app.vendors.tiktok_creative_center import TikTokCreativeCenterClient

    respx.get("https://ads.tiktok.com/creative_radar_api/v1/top_ads/v2/list").mock(
        return_value=httpx.Response(200, json={"unexpected": "shape"})
    )

    client = TikTokCreativeCenterClient()
    out = await client.fetch_top_ads(industry="activewear")
    assert out == {"data": []}


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__tiktok_cc__count_aggregates_across_industries() -> None:
    from app.vendors.tiktok_creative_center import TikTokCreativeCenterClient

    route = respx.get("https://ads.tiktok.com/creative_radar_api/v1/top_ads/v2/list").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": [
                        {"brand_name": "Alo Yoga"},
                        {"brand_name": "Gymshark"},
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "data": [
                        {"brand_name": "Alo Yoga"},  # cross-industry
                        {"brand_name": "Rhode"},
                    ]
                },
            ),
        ]
    )

    client = TikTokCreativeCenterClient()
    out = await client.count_active_advertisers_per_industry(
        industries=["activewear", "beauty"], region="US"
    )
    assert route.call_count == 2
    assert out["Alo Yoga"]["ad_count"] == 2
    assert set(out["Alo Yoga"]["industries"]) == {"activewear", "beauty"}
    assert out["Gymshark"]["ad_count"] == 1
    assert out["Rhode"]["ad_count"] == 1
