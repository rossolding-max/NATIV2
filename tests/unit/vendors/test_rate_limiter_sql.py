"""Unit tests for the rate-limiter Lua script + Python wrapper.

Uses a fake ``aioredis`` client because the focus is on the Lua eval call
semantics, not Redis itself. The Lua script's atomicity is verified
separately in the integration test against a real Redis container (in
``tests/integration/vendors/test_smartlead_rate_limits.py``).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.errors import IntegrationRateLimitError
from app.vendors import _rate_limiter
from app.vendors._rate_limiter import check_rate_limit


@pytest.fixture(autouse=True)
def _reset_redis() -> Any:  # pyright: ignore[reportUnusedFunction]
    _rate_limiter.reset_client_for_tests()
    yield
    _rate_limiter.reset_client_for_tests()


async def test_unit__rate_limiter__under_quota__no_raise() -> None:
    mock_client = AsyncMock()
    mock_client.eval = AsyncMock(return_value=[1, 0.0])
    with patch.object(_rate_limiter, "get_redis_client", return_value=mock_client):
        await check_rate_limit("smartlead", "global", max_per_period=60, period_seconds=60)
    mock_client.eval.assert_awaited_once()


async def test_unit__rate_limiter__quota_exhausted__raises_with_retry_after() -> None:
    mock_client = AsyncMock()
    mock_client.eval = AsyncMock(return_value=[0, 2.5])
    with (
        patch.object(_rate_limiter, "get_redis_client", return_value=mock_client),
        pytest.raises(IntegrationRateLimitError) as exc_info,
    ):
        await check_rate_limit("exa", "global", max_per_period=5, period_seconds=10)

    assert exc_info.value.detail["vendor"] == "exa"
    assert exc_info.value.detail["retry_after_seconds"] == pytest.approx(2.5)


async def test_unit__rate_limiter__namespaced_keys() -> None:
    """Vendor + bucket combine into the Redis key namespace."""
    mock_client = AsyncMock()
    mock_client.eval = AsyncMock(return_value=[1, 0.0])
    with patch.object(_rate_limiter, "get_redis_client", return_value=mock_client):
        await check_rate_limit("apollo", "talent-9876", max_per_period=10, period_seconds=60)

    # The Lua script is invoked with one key — verify the namespace.
    call_args = mock_client.eval.await_args_list[0]
    # Signature: eval(script, num_keys, key, *argv) → key is positional arg #2.
    assert call_args.args[2] == "ratelimit:apollo:talent-9876"
