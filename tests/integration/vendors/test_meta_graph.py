"""Integration tests for ``MetaGraphClient`` (respx-mocked)."""

from __future__ import annotations

import hashlib
import hmac
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import get_settings
from app.errors import IntegrationError, IntegrationRateLimitError
from app.vendors import _http_client


@pytest.fixture(autouse=True)
def _vendor_settings() -> Any:  # pyright: ignore[reportUnusedFunction]
    s = get_settings()
    saved_id = s.meta_app_id
    saved_secret = s.meta_app_secret
    saved_verify = s.meta_webhook_verify_token
    s.meta_app_id = "meta-app-id-test"
    s.meta_app_secret = SecretStr("meta-app-secret-test")
    s.meta_webhook_verify_token = SecretStr("verify-token-xyz")
    _http_client.reset_client_for_tests()
    yield
    s.meta_app_id = saved_id
    s.meta_app_secret = saved_secret
    s.meta_webhook_verify_token = saved_verify
    _http_client.reset_client_for_tests()


@pytest.fixture
def _rate_limit_ok() -> Any:  # pyright: ignore[reportUnusedFunction]
    async def _noop(
        _vendor: str, _bucket: str, *, max_per_period: int, period_seconds: int
    ) -> None:
        return None

    with patch("app.vendors.meta_graph.check_rate_limit", _noop):
        yield


def test_integration__authorize_url__contains_default_scopes() -> None:
    from app.vendors.meta_graph import MetaGraphClient

    client = MetaGraphClient()
    url = client.build_authorize_url(redirect_uri="https://app.example.com/callback", state="abc")
    assert "instagram.com/oauth/authorize" in url
    assert "instagram_business_basic" in url
    assert "instagram_business_content_publish" in url
    assert "instagram_business_manage_insights" in url
    assert "state=abc" in url


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__exchange_code__posts_form_payload() -> None:
    from app.vendors.meta_graph import MetaGraphClient

    route = respx.post("https://api.instagram.com/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "short-lived-xyz", "user_id": 1})
    )
    client = MetaGraphClient()
    result = await client.exchange_code("code-abc", "https://app.example.com/callback")
    assert result["access_token"] == "short-lived-xyz"
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__list_media__hits_graph_v22() -> None:
    from app.vendors.meta_graph import MetaGraphClient

    route = respx.get("https://graph.facebook.com/v22.0/ig-user-1/media").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client = MetaGraphClient()
    result = await client.list_media("ig-user-1", "long-lived-token")
    assert result == {"data": []}
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__get_media_insights__includes_metric_param() -> None:
    from app.vendors.meta_graph import MetaGraphClient

    route = respx.get("https://graph.facebook.com/v22.0/media-1/insights").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    client = MetaGraphClient()
    await client.get_media_insights("media-1", "long-lived-token")
    assert route.called
    assert "metric=" in str(route.calls[0].request.url)


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__refresh_long_lived_token__ig_refresh_grant() -> None:
    from app.vendors.meta_graph import MetaGraphClient

    route = respx.get("https://graph.facebook.com/v22.0/refresh_access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "new-token", "expires_in": 5184000})
    )
    client = MetaGraphClient()
    result = await client.refresh_long_lived_token("old-token")
    assert result["access_token"] == "new-token"
    assert "ig_refresh_token" in str(route.calls[0].request.url)


def test_integration__verify_webhook__valid_signature_returns_true() -> None:
    from app.vendors.meta_graph import MetaGraphClient

    client = MetaGraphClient()
    body = b'{"object":"instagram","entry":[]}'
    sig = "sha256=" + hmac.new(b"meta-app-secret-test", body, hashlib.sha256).hexdigest()
    assert client.verify_webhook(body, sig) is True


def test_integration__verify_webhook__missing_prefix_returns_false() -> None:
    from app.vendors.meta_graph import MetaGraphClient

    client = MetaGraphClient()
    body = b'{"object":"instagram"}'
    sig = hmac.new(b"meta-app-secret-test", body, hashlib.sha256).hexdigest()
    # Without the sha256= prefix it must reject.
    assert client.verify_webhook(body, sig) is False


def test_integration__subscription_challenge__matches_verify_token() -> None:
    from app.vendors.meta_graph import MetaGraphClient

    client = MetaGraphClient()
    echoed = client.verify_subscription_challenge("subscribe", "verify-token-xyz", "1234")
    assert echoed == "1234"


def test_integration__subscription_challenge__wrong_token_returns_none() -> None:
    from app.vendors.meta_graph import MetaGraphClient

    client = MetaGraphClient()
    assert client.verify_subscription_challenge("subscribe", "wrong", "1234") is None


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__429_maps_to_rate_limit_error() -> None:
    from app.vendors.meta_graph import MetaGraphClient

    respx.get("https://graph.facebook.com/v22.0/ig-user-1/media").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "120"})
    )
    client = MetaGraphClient()
    with pytest.raises(IntegrationRateLimitError):
        await client.list_media("ig-user-1", "token")


def test_integration__missing_credentials_raises_at_construction() -> None:
    from app.vendors.meta_graph import MetaGraphClient

    s = get_settings()
    saved_id = s.meta_app_id
    saved_secret = s.meta_app_secret
    s.meta_app_id = None
    s.meta_app_secret = None
    try:
        with pytest.raises(IntegrationError):
            MetaGraphClient()
    finally:
        s.meta_app_id = saved_id
        s.meta_app_secret = saved_secret
