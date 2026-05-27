"""Integration tests for ``TikTokClient`` including PKCE flow."""

from __future__ import annotations

import base64
import hashlib
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import get_settings
from app.errors import IntegrationError, IntegrationRateLimitError
from app.vendors import _http_client
from app.vendors.tiktok import generate_pkce_pair


@pytest.fixture(autouse=True)
def _vendor_settings() -> Any:  # pyright: ignore[reportUnusedFunction]
    s = get_settings()
    saved_key = s.tiktok_client_key
    saved_secret = s.tiktok_client_secret
    s.tiktok_client_key = "tt-client-key-test"
    s.tiktok_client_secret = SecretStr("tt-client-secret-test")
    _http_client.reset_client_for_tests()
    yield
    s.tiktok_client_key = saved_key
    s.tiktok_client_secret = saved_secret
    _http_client.reset_client_for_tests()


@pytest.fixture
def _rate_limit_ok() -> Any:  # pyright: ignore[reportUnusedFunction]
    async def _noop(
        _vendor: str, _bucket: str, *, max_per_period: int, period_seconds: int
    ) -> None:
        return None

    with patch("app.vendors.tiktok.check_rate_limit", _noop):
        yield


def test_integration__pkce_pair__challenge_is_sha256_of_verifier() -> None:
    verifier, challenge = generate_pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    assert challenge == expected
    assert 43 <= len(verifier) <= 128  # RFC 7636 PKCE constraints
    assert "=" not in challenge


def test_integration__pkce_pair__verifiers_are_unique() -> None:
    seen: set[str] = set()
    for _ in range(20):
        verifier, _ = generate_pkce_pair()
        assert verifier not in seen
        seen.add(verifier)


def test_integration__authorize_url__includes_pkce_params() -> None:
    from app.vendors.tiktok import TikTokClient

    client = TikTokClient()
    _, challenge = generate_pkce_pair()
    url = client.build_authorize_url(
        redirect_uri="https://app.example.com/callback",
        state="abc",
        code_challenge=challenge,
    )
    assert "tiktok.com/v2/auth/authorize" in url
    assert "code_challenge_method=S256" in url
    assert f"code_challenge={challenge}" in url
    assert "state=abc" in url
    assert "scope=user.info.basic+video.list" in url


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__exchange_code__sends_verifier_as_form_param() -> None:
    from app.vendors.tiktok import TikTokClient

    route = respx.post("https://open.tiktokapis.com/v2/oauth/token/").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "expires_in": 86400,
                "open_id": "user-1",
            },
        )
    )
    client = TikTokClient()
    result = await client.exchange_code(
        "code-xyz", "https://app.example.com/callback", "verifier-stored-in-redis"
    )
    assert result["access_token"] == "at-1"
    assert route.called
    body = route.calls[0].request.content.decode()
    assert "code_verifier=verifier-stored-in-redis" in body
    assert "grant_type=authorization_code" in body


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__refresh_token__hits_token_endpoint() -> None:
    from app.vendors.tiktok import TikTokClient

    route = respx.post("https://open.tiktokapis.com/v2/oauth/token/").mock(
        return_value=httpx.Response(200, json={"access_token": "new", "refresh_token": "rt-2"})
    )
    client = TikTokClient()
    result = await client.refresh_token("old-refresh")
    assert result["access_token"] == "new"
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__list_videos__bearer_auth_header() -> None:
    from app.vendors.tiktok import TikTokClient

    route = respx.post("https://open.tiktokapis.com/v2/video/list/").mock(
        return_value=httpx.Response(200, json={"data": {"videos": []}})
    )
    client = TikTokClient()
    await client.list_videos("access-token-x")
    assert route.called
    assert route.calls[0].request.headers["Authorization"] == "Bearer access-token-x"


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__query_video__by_ids() -> None:
    from app.vendors.tiktok import TikTokClient

    route = respx.post("https://open.tiktokapis.com/v2/video/query/").mock(
        return_value=httpx.Response(200, json={"data": {"videos": []}})
    )
    client = TikTokClient()
    await client.query_video("token", ["v1", "v2"])
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__429_maps_to_rate_limit_error() -> None:
    from app.vendors.tiktok import TikTokClient

    respx.get("https://open.tiktokapis.com/v2/user/info/").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "60"})
    )
    client = TikTokClient()
    with pytest.raises(IntegrationRateLimitError):
        await client.get_user_info("token")


def test_integration__missing_credentials_raises_at_construction() -> None:
    from app.vendors.tiktok import TikTokClient

    s = get_settings()
    saved_key = s.tiktok_client_key
    saved_secret = s.tiktok_client_secret
    s.tiktok_client_key = None
    s.tiktok_client_secret = None
    try:
        with pytest.raises(IntegrationError):
            TikTokClient()
    finally:
        s.tiktok_client_key = saved_key
        s.tiktok_client_secret = saved_secret
