"""Integration tests for ``ApolloClient`` (respx-mocked)."""

from __future__ import annotations

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
    saved = s.apollo_api_key
    s.apollo_api_key = SecretStr("sk-apollo-test")
    _http_client.reset_client_for_tests()
    yield
    s.apollo_api_key = saved
    _http_client.reset_client_for_tests()


@pytest.fixture
def _rate_limit_ok() -> Any:  # pyright: ignore[reportUnusedFunction]
    async def _noop(
        _vendor: str, _bucket: str, *, max_per_period: int, period_seconds: int
    ) -> None:
        return None

    with patch("app.vendors.apollo.check_rate_limit", _noop):
        yield


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__search_people__by_domain_and_titles() -> None:
    from app.vendors.apollo import ApolloClient

    route = respx.post("https://api.apollo.io/v1/mixed_people/search").mock(
        return_value=httpx.Response(200, json={"people": [{"id": "p1"}]})
    )

    client = ApolloClient()
    result = await client.search_people(
        domain="acme.com",
        titles=["Head of Marketing", "VP Marketing"],
        seniorities=["director", "vp"],
    )

    assert result == {"people": [{"id": "p1"}]}
    assert route.called
    req = route.calls[0].request
    assert req.headers["X-Api-Key"] == "sk-apollo-test"


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__match_person__by_linkedin_url() -> None:
    from app.vendors.apollo import ApolloClient

    route = respx.post("https://api.apollo.io/v1/people/match").mock(
        return_value=httpx.Response(200, json={"person": {"id": "p1"}})
    )

    client = ApolloClient()
    result = await client.match_person(linkedin_url="https://linkedin.com/in/jane")
    assert result == {"person": {"id": "p1"}}
    assert route.called


async def test_integration__match_person__requires_at_least_one_signal() -> None:
    from app.vendors.apollo import ApolloClient

    client = ApolloClient()
    with pytest.raises(IntegrationError):
        await client.match_person()


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__enrich_organization__by_domain() -> None:
    from app.vendors.apollo import ApolloClient

    route = respx.post("https://api.apollo.io/v1/organizations/enrich").mock(
        return_value=httpx.Response(200, json={"organization": {"name": "Acme"}})
    )

    client = ApolloClient()
    result = await client.enrich_organization("acme.com")
    assert result["organization"]["name"] == "Acme"
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__429_maps_to_rate_limit_error() -> None:
    from app.vendors.apollo import ApolloClient

    respx.post("https://api.apollo.io/v1/organizations/enrich").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "60"})
    )

    client = ApolloClient()
    with pytest.raises(IntegrationRateLimitError):
        await client.enrich_organization("acme.com")


def test_integration__missing_api_key_raises_at_construction() -> None:
    from app.vendors.apollo import ApolloClient

    s = get_settings()
    saved = s.apollo_api_key
    s.apollo_api_key = None
    try:
        with pytest.raises(IntegrationError):
            ApolloClient()
    finally:
        s.apollo_api_key = saved
