"""Integration tests for ``LinkedInScraperClient`` (RapidAPI gateway)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import settings as app_settings
from app.errors import IntegrationError, IntegrationRateLimitError
from app.vendors import _http_client


@pytest.fixture(autouse=True)
def _vendor_settings(monkeypatch: pytest.MonkeyPatch) -> Any:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.setattr(app_settings, "rapidapi_key", SecretStr("rapidapi-test-key"))
    _http_client.reset_client_for_tests()
    yield
    _http_client.reset_client_for_tests()


@pytest.fixture
def _rate_limit_ok() -> Any:  # pyright: ignore[reportUnusedFunction]
    async def _noop(
        _vendor: str, _bucket: str, *, max_per_period: int, period_seconds: int
    ) -> None:
        return None

    with patch("app.vendors.linkedin.check_rate_limit", _noop):
        yield


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__get_profile_by_url__sends_required_headers() -> None:
    from app.vendors.linkedin import LinkedInScraperClient

    route = respx.get("https://linkedin-data-api.p.rapidapi.com/").mock(
        return_value=httpx.Response(
            200, json={"firstName": "Jane", "lastName": "Doe", "headline": "CMO"}
        )
    )

    client = LinkedInScraperClient()
    result = await client.get_profile_by_url("https://linkedin.com/in/jane-doe")

    assert result["firstName"] == "Jane"
    assert route.called
    req = route.calls[0].request
    # Both RapidAPI gateway headers must be present.
    assert req.headers["x-rapidapi-key"] == "rapidapi-test-key"
    assert req.headers["x-rapidapi-host"] == "linkedin-data-api.p.rapidapi.com"


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__get_company_by_domain__hits_correct_endpoint() -> None:
    from app.vendors.linkedin import LinkedInScraperClient

    route = respx.get("https://linkedin-data-api.p.rapidapi.com/get-company-by-domain").mock(
        return_value=httpx.Response(200, json={"name": "Acme Inc"})
    )

    client = LinkedInScraperClient()
    result = await client.get_company_by_domain("acme.com")
    assert result["name"] == "Acme Inc"
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__get_recent_posts__respects_limit() -> None:
    from app.vendors.linkedin import LinkedInScraperClient

    route = respx.get("https://linkedin-data-api.p.rapidapi.com/get-profile-posts").mock(
        return_value=httpx.Response(200, json={"posts": []})
    )

    client = LinkedInScraperClient()
    await client.get_recent_posts("jane-doe", limit=3)
    assert route.called
    assert "limit=3" in str(route.calls[0].request.url)


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__429_maps_to_rate_limit_error() -> None:
    from app.vendors.linkedin import LinkedInScraperClient

    respx.get("https://linkedin-data-api.p.rapidapi.com/").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )

    client = LinkedInScraperClient()
    with pytest.raises(IntegrationRateLimitError):
        await client.get_profile_by_url("https://linkedin.com/in/x")


def test_integration__missing_rapidapi_key_raises_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.vendors.linkedin import LinkedInScraperClient

    monkeypatch.setattr(app_settings, "rapidapi_key", None)
    monkeypatch.setattr(app_settings, "linkedin_api_key", None)
    with pytest.raises(IntegrationError):
        LinkedInScraperClient()


def test_integration__legacy_linkedin_api_key_backfills_rapidapi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Until M5, LINKEDIN_API_KEY-only configs still construct successfully.

    The backfill happens in the Settings model_validator on construction.
    In this test we simulate the post-validator state (rapidapi_key takes
    its value from linkedin_api_key) and confirm the *client* succeeds.
    """
    from app.vendors.linkedin import LinkedInScraperClient

    monkeypatch.setattr(app_settings, "rapidapi_key", SecretStr("legacy-set-value"))
    monkeypatch.setattr(app_settings, "linkedin_api_key", SecretStr("legacy-set-value"))
    LinkedInScraperClient()
