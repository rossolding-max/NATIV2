"""Integration tests for ``ExaClient`` (respx-mocked)."""

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
    monkeypatch.setattr(app_settings, "exa_api_key", SecretStr("sk-exa-test"))
    _http_client.reset_client_for_tests()
    yield
    _http_client.reset_client_for_tests()


@pytest.fixture
def _rate_limit_ok() -> Any:  # pyright: ignore[reportUnusedFunction]
    async def _noop(
        _vendor: str, _bucket: str, *, max_per_period: int, period_seconds: int
    ) -> None:
        return None

    with patch("app.vendors.exa.check_rate_limit", _noop):
        yield


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__search__happy_path() -> None:
    from app.vendors.exa import ExaClient

    route = respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(
            200, json={"results": [{"url": "https://example.com", "title": "Example"}]}
        )
    )

    client = ExaClient()
    result = await client.search("athleisure direct-to-consumer brands", num_results=5)

    assert "results" in result
    assert route.called
    req = route.calls[0].request
    body = req.read().decode()
    assert "numResults" in body
    assert "5" in body
    # API key in header, not query string.
    assert req.headers["x-api-key"] == "sk-exa-test"


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__find_similar__hits_correct_endpoint() -> None:
    from app.vendors.exa import ExaClient

    route = respx.post("https://api.exa.ai/findSimilar").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    client = ExaClient()
    result = await client.find_similar("https://nike.com")
    assert result == {"results": []}
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__get_contents__sends_url_list() -> None:
    from app.vendors.exa import ExaClient

    route = respx.post("https://api.exa.ai/contents").mock(
        return_value=httpx.Response(200, json={"contents": []})
    )

    client = ExaClient()
    await client.get_contents(["https://a.com", "https://b.com"])
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__429_maps_to_rate_limit_error() -> None:
    from app.vendors.exa import ExaClient

    respx.post("https://api.exa.ai/search").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "15"})
    )

    client = ExaClient()
    with pytest.raises(IntegrationRateLimitError) as exc_info:
        await client.search("query")
    assert exc_info.value.detail["retry_after_seconds"] == 15.0


def test_integration__missing_api_key_raises_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.vendors.exa import ExaClient

    monkeypatch.setattr(app_settings, "exa_api_key", None)
    with pytest.raises(IntegrationError):
        ExaClient()
