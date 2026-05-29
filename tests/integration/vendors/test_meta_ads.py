"""Integration tests for ``MetaAdsClient`` (respx-mocked)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import settings as app_settings
from app.errors import IntegrationError
from app.vendors import _http_client


@pytest.fixture(autouse=True)
def _vendor_settings(monkeypatch: pytest.MonkeyPatch) -> Any:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.setattr(app_settings, "meta_ads_api_token", SecretStr("test-meta-token"))
    _http_client.reset_client_for_tests()
    yield
    _http_client.reset_client_for_tests()


@pytest.fixture
def _rate_limit_ok() -> Any:  # pyright: ignore[reportUnusedFunction]
    async def _noop(
        _vendor: str, _bucket: str, *, max_per_period: int, period_seconds: int
    ) -> None:
        return None

    with patch("app.vendors.meta_ads.check_rate_limit", _noop):
        yield


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__meta_ads__search_ads_happy_path() -> None:
    from app.vendors.meta_ads import MetaAdsClient

    route = respx.get("https://graph.facebook.com/v22.0/ads_archive").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "ad_1",
                        "page_name": "Alo Yoga",
                        "page_id": "100",
                        "ad_snapshot_url": "https://fb.com/ad/1",
                        "languages": ["en"],
                    }
                ],
            },
        )
    )

    client = MetaAdsClient()
    out = await client.search_ads(search_terms="activewear", countries=["US"])
    assert "data" in out
    assert len(out["data"]) == 1
    assert route.called
    req = route.calls[0].request
    # Auth token + filter params land in the query string.
    assert "access_token=test-meta-token" in str(req.url)
    assert "search_terms=activewear" in str(req.url)
    assert "ad_reached_countries=US" in str(req.url)


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__meta_ads__count_aggregates_per_advertiser() -> None:
    from app.vendors.meta_ads import MetaAdsClient

    respx.get("https://graph.facebook.com/v22.0/ads_archive").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"page_name": "Alo Yoga", "page_id": "100"},
                    {"page_name": "Alo Yoga", "page_id": "100"},
                    {"page_name": "Gymshark", "page_id": "200"},
                    {"page_name": "", "page_id": "300"},  # dropped
                ],
            },
        )
    )

    client = MetaAdsClient()
    out = await client.count_active_ads_per_advertiser(
        search_terms="activewear", countries=["US"]
    )
    assert out["Alo Yoga"]["ad_count"] == 2
    assert out["Alo Yoga"]["page_id"] == "100"
    assert out["Gymshark"]["ad_count"] == 1
    assert "" not in out  # empty page_name filtered out


@pytest.mark.usefixtures("_rate_limit_ok")
def test_integration__meta_ads__missing_token_raises() -> None:
    """Constructor enforces that the token is configured."""
    from app.vendors.meta_ads import MetaAdsClient

    with (
        patch.object(app_settings, "meta_ads_api_token", None),
        pytest.raises(IntegrationError, match="META_ADS_API_TOKEN"),
    ):
        MetaAdsClient()


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__meta_ads__date_min_forwarded_in_query() -> None:
    from app.vendors.meta_ads import MetaAdsClient

    route = respx.get("https://graph.facebook.com/v22.0/ads_archive").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    client = MetaAdsClient()
    await client.search_ads(
        search_terms="activewear",
        countries=["US"],
        ad_delivery_date_min="2026-04-29",
    )
    assert route.called
    req = route.calls[0].request
    assert "ad_delivery_date_min=2026-04-29" in str(req.url)
