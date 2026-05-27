"""Integration tests for ``SmartleadClient``.

Mocks HTTP via ``respx``; bypasses rate-limit + redis interactions with the
``_rate_limit_ok`` fixture. Real-network tests live in
``tests/live/vendors/test_smartlead_live.py``.

Fixtures mutate ``app.config.settings`` via ``monkeypatch.setattr`` — NOT
``get_settings()``. Other M0/M1/M2 integration tests call
``get_settings.cache_clear()``, which divorces the new cached Settings from
the module-level ``app.config.settings`` that vendor clients capture at
import. Mutating the module-level binding directly keeps everything in
sync regardless of cache state.
"""

from __future__ import annotations

import hashlib
import hmac
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
    """Provide Smartlead API + webhook secret for the duration of the test."""
    monkeypatch.setattr(app_settings, "smartlead_api_key", SecretStr("sk-smartlead-test"))
    monkeypatch.setattr(app_settings, "smartlead_webhook_secret", SecretStr("webhook-secret-xyz"))
    _http_client.reset_client_for_tests()
    yield
    _http_client.reset_client_for_tests()


@pytest.fixture
def _rate_limit_ok() -> Any:  # pyright: ignore[reportUnusedFunction]
    """Bypass Redis-backed rate limiting in respx-mocked tests."""

    async def _noop(
        _vendor: str, _bucket: str, *, max_per_period: int, period_seconds: int
    ) -> None:
        return None

    with patch("app.vendors.smartlead.check_rate_limit", _noop):
        yield


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__create_campaign__happy_path() -> None:
    from app.vendors.smartlead import SmartleadClient

    route = respx.post("https://server.smartlead.ai/api/v1/campaigns/create").mock(
        return_value=httpx.Response(200, json={"id": "camp_abc", "name": "Acme Q3"})
    )

    client = SmartleadClient()
    response = await client.create_campaign("Acme Q3")

    assert response == {"id": "camp_abc", "name": "Acme Q3"}
    assert route.called
    # API key on the query string (Smartlead quirk).
    assert "api_key=sk-smartlead-test" in str(route.calls[0].request.url)


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__add_leads__hits_correct_endpoint() -> None:
    from app.vendors.smartlead import SmartleadClient

    route = respx.post("https://server.smartlead.ai/api/v1/campaigns/camp_abc/leads").mock(
        return_value=httpx.Response(200, json={"upload_count": 2})
    )

    client = SmartleadClient()
    result = await client.add_leads(
        "camp_abc",
        [
            {"email": "a@example.com", "first_name": "Alice"},
            {"email": "b@example.com", "first_name": "Bob"},
        ],
    )

    assert result == {"upload_count": 2}
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__rate_limit_response_maps_to_error() -> None:
    from app.vendors.smartlead import SmartleadClient

    respx.post("https://server.smartlead.ai/api/v1/campaigns/create").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )

    client = SmartleadClient()
    with pytest.raises(IntegrationRateLimitError) as exc_info:
        await client.create_campaign("Acme Q3")

    assert exc_info.value.detail["retry_after_seconds"] == 30.0


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__server_error_after_retries_raises() -> None:
    """5xx is retried; after exhaustion it surfaces as IntegrationError."""
    from app.vendors.smartlead import SmartleadClient

    respx.post("https://server.smartlead.ai/api/v1/campaigns/create").mock(
        return_value=httpx.Response(503, text="upstream down")
    )

    # Patch tenacity's sleep so we don't wait 1+2+4 seconds during the test.
    async def _no_sleep(_seconds: float) -> None:
        return None

    client = SmartleadClient()
    with (
        patch("asyncio.sleep", _no_sleep),
        patch("tenacity.nap.time.sleep"),
        pytest.raises(IntegrationError),
    ):
        await client.create_campaign("Acme Q3")


def test_integration__webhook_verify__valid_signature__returns_true() -> None:
    from app.vendors.smartlead import SmartleadClient

    client = SmartleadClient()
    body = b'{"event_type":"opened","lead_id":"l_1"}'
    sig = hmac.new(b"webhook-secret-xyz", body, hashlib.sha256).hexdigest()

    assert client.verify_webhook(body, sig) is True


def test_integration__webhook_verify__tampered_body__returns_false() -> None:
    from app.vendors.smartlead import SmartleadClient

    client = SmartleadClient()
    sig = hmac.new(b"webhook-secret-xyz", b'{"event_type":"opened"}', hashlib.sha256).hexdigest()
    assert client.verify_webhook(b'{"event_type":"clicked"}', sig) is False


def test_integration__webhook_verify__no_secret_configured__returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.vendors.smartlead import SmartleadClient

    monkeypatch.setattr(app_settings, "smartlead_webhook_secret", None)
    client = SmartleadClient()
    assert client.verify_webhook(b"x", "deadbeef") is False


def test_integration__parse_engagement_event__extracts_fields() -> None:
    from app.vendors.smartlead import SmartleadClient

    body = {
        "event_type": "EMAIL_OPENED",
        "campaign_id": "camp_1",
        "lead_id": "lead_42",
        "lead_email": "x@example.com",
        "occurred_at": "2026-05-28T09:00:00Z",
        "subject": "ignored extra",
    }
    parsed = SmartleadClient.parse_engagement_event(body)
    assert parsed["event_type"] == "EMAIL_OPENED"
    assert parsed["campaign_id"] == "camp_1"
    assert parsed["lead_id"] == "lead_42"
    assert parsed["raw"] is body


def test_integration__missing_api_key_raises_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.vendors.smartlead import SmartleadClient

    monkeypatch.setattr(app_settings, "smartlead_api_key", None)
    with pytest.raises(IntegrationError):
        SmartleadClient()
