"""Unit tests for ``app.vendors._retry``.

Don't sleep wall-clock — patch tenacity's sleep so retries finish instantly.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from app.errors import (
    BusinessRuleError,
    IntegrationError,
    IntegrationRateLimitError,
    IntegrationTimeoutError,
)
from app.vendors._retry import _should_retry, async_vendor_retry


@pytest.fixture(autouse=True)
def _patch_tenacity_sleep() -> Any:  # pyright: ignore[reportUnusedFunction]
    """Make ``AsyncRetrying`` skip its wall-clock sleep between attempts."""

    async def _no_sleep(_seconds: float) -> None:
        return None

    with patch("tenacity.nap.time.sleep"), patch("asyncio.sleep", _no_sleep):
        yield


def test_unit__should_retry__on_timeout__returns_true() -> None:
    assert _should_retry(IntegrationTimeoutError("x")) is True


def test_unit__should_retry__on_rate_limit__returns_true() -> None:
    assert _should_retry(IntegrationRateLimitError("x")) is True


def test_unit__should_retry__on_httpx_connect_error__returns_true() -> None:
    assert _should_retry(httpx.ConnectError("boom")) is True


def test_unit__should_retry__on_5xx__returns_true() -> None:
    exc = IntegrationError("x", detail={"status": 503})
    assert _should_retry(exc) is True


def test_unit__should_retry__on_4xx__returns_false() -> None:
    exc = IntegrationError("x", detail={"status": 404})
    assert _should_retry(exc) is False


def test_unit__should_retry__on_non_integration_error__returns_false() -> None:
    assert _should_retry(BusinessRuleError("nope")) is False


async def test_unit__retries_until_success() -> None:
    attempts = {"n": 0}

    @async_vendor_retry(max_attempts=3, base_delay_seconds=0.001)
    async def _flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise IntegrationTimeoutError("transient")
        return "ok"

    assert await _flaky() == "ok"
    assert attempts["n"] == 3


async def test_unit__raises_after_max_attempts() -> None:
    attempts = {"n": 0}

    @async_vendor_retry(max_attempts=2, base_delay_seconds=0.001)
    async def _always_times_out() -> str:
        attempts["n"] += 1
        raise IntegrationTimeoutError("nope")

    with pytest.raises(IntegrationTimeoutError):
        await _always_times_out()
    assert attempts["n"] == 2


async def test_unit__non_retryable_error_raised_immediately() -> None:
    attempts = {"n": 0}

    @async_vendor_retry(max_attempts=3, base_delay_seconds=0.001)
    async def _validation_failure() -> str:
        attempts["n"] += 1
        raise BusinessRuleError("don't retry me")

    with pytest.raises(BusinessRuleError):
        await _validation_failure()
    assert attempts["n"] == 1
