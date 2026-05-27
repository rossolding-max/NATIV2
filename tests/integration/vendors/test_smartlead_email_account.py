"""Integration tests for the M4 additions to ``SmartleadClient``.

Covers ``create_email_account``, ``get_email_account``,
``update_warmup_settings``, ``get_warmup_stats`` against the verified
``/api/v1/email-accounts/*`` paths.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx
from pydantic import SecretStr

from app.config import settings as app_settings
from app.errors import IntegrationRateLimitError
from app.vendors import _http_client


@pytest.fixture(autouse=True)
def _vendor_settings(monkeypatch: pytest.MonkeyPatch) -> Any:  # pyright: ignore[reportUnusedFunction]
    monkeypatch.setattr(app_settings, "smartlead_api_key", SecretStr("sk-smartlead-test"))
    _http_client.reset_client_for_tests()
    yield
    _http_client.reset_client_for_tests()


@pytest.fixture
def _rate_limit_ok() -> Any:  # pyright: ignore[reportUnusedFunction]
    async def _noop(
        _vendor: str, _bucket: str, *, max_per_period: int, period_seconds: int
    ) -> None:
        return None

    with patch("app.vendors.smartlead.check_rate_limit", _noop):
        yield


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__create_email_account__posts_smtp_config() -> None:
    from app.vendors.smartlead import SmartleadClient

    route = respx.post("https://server.smartlead.ai/api/v1/email-accounts/save").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "id": 42,
                    "from_email": "sarah@acme.com",
                    "is_smtp_success": True,
                    "is_imap_success": True,
                },
            },
        )
    )

    client = SmartleadClient()
    result = await client.create_email_account(
        from_name="Sarah",
        from_email="sarah@acme.com",
        user_name="sarah@acme.com",
        password="app-specific-pw",
        smtp_host="smtp.gmail.com",
        smtp_port=465,
        imap_host="imap.gmail.com",
        imap_port=993,
    )

    assert result["data"]["id"] == 42
    assert route.called
    assert "api_key=sk-smartlead-test" in str(route.calls[0].request.url)


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__get_email_account__returns_full_record() -> None:
    from app.vendors.smartlead import SmartleadClient

    route = respx.get("https://server.smartlead.ai/api/v1/email-accounts/42/").mock(
        return_value=httpx.Response(
            200,
            json={"id": 42, "from_email": "sarah@acme.com", "warmup_details": {"status": "active"}},
        )
    )
    client = SmartleadClient()
    result = await client.get_email_account(42)

    assert result["warmup_details"]["status"] == "active"
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__update_warmup_settings__posts_config() -> None:
    from app.vendors.smartlead import SmartleadClient

    route = respx.post("https://server.smartlead.ai/api/v1/email-accounts/42/warmup").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    client = SmartleadClient()
    await client.update_warmup_settings(
        42, warmup_enabled=True, total_warmup_per_day=20, daily_rampup=2, reply_rate_percentage=30
    )
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__get_warmup_stats__returns_7day_summary() -> None:
    from app.vendors.smartlead import SmartleadClient

    route = respx.get("https://server.smartlead.ai/api/v1/email-accounts/42/warmup-stats").mock(
        return_value=httpx.Response(200, json={"sent": 140, "inbox": 132, "spam": 8})
    )
    client = SmartleadClient()
    result = await client.get_warmup_stats(42)
    assert result["inbox"] == 132
    assert route.called


@pytest.mark.usefixtures("_rate_limit_ok")
@respx.mock
async def test_integration__email_account_429_maps_to_rate_limit_error() -> None:
    from app.vendors.smartlead import SmartleadClient

    respx.post("https://server.smartlead.ai/api/v1/email-accounts/save").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "30"})
    )

    client = SmartleadClient()
    with pytest.raises(IntegrationRateLimitError):
        await client.create_email_account(
            from_name="Sarah",
            from_email="sarah@acme.com",
            user_name="sarah@acme.com",
            password="app-pw",
            smtp_host="smtp.gmail.com",
            smtp_port=465,
            imap_host="imap.gmail.com",
            imap_port=993,
        )
