"""Tenacity-based async retry decorator factory for vendor wrappers.

Configurable per-vendor: retries on connect timeouts, 5xx, and 429. Honors
the ``Retry-After`` header when present on 429 (via a custom wait strategy).

The factory returns a fresh decorator on each call so different vendors can
hold different policies without sharing module state.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.errors import IntegrationError, IntegrationRateLimitError, IntegrationTimeoutError

_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_BASE_DELAY_SECONDS = 1.0
_DEFAULT_MAX_DELAY_SECONDS = 60.0
_DEFAULT_EXP_MULTIPLIER = 1.0


def _should_retry(exc: BaseException) -> bool:
    """Retry on connect timeouts, transient 5xx, and 429.

    Permanent 4xx errors (auth, validation) are NOT retried.
    """
    if isinstance(exc, IntegrationTimeoutError | IntegrationRateLimitError):
        return True
    if isinstance(exc, httpx.ConnectError | httpx.ReadTimeout | httpx.ConnectTimeout):
        return True
    if isinstance(exc, IntegrationError):
        detail = getattr(exc, "detail", {}) or {}
        status = detail.get("status")
        return isinstance(status, int) and 500 <= status < 600
    return False


def _retry_after_seconds(retry_state: RetryCallState) -> float | None:
    """Read ``Retry-After`` from the exception's ``detail`` dict, if present."""
    if retry_state.outcome is None:
        return None
    exc = retry_state.outcome.exception()
    if exc is None:
        return None
    detail = getattr(exc, "detail", {}) or {}
    retry_after = detail.get("retry_after_seconds")
    if isinstance(retry_after, int | float) and retry_after > 0:
        return float(retry_after)
    return None


def _combined_wait(retry_state: RetryCallState) -> float:
    """Use ``Retry-After`` if the vendor provided it; else exponential backoff."""
    server_hint = _retry_after_seconds(retry_state)
    if server_hint is not None:
        return min(server_hint, _DEFAULT_MAX_DELAY_SECONDS)
    return wait_exponential(
        multiplier=_DEFAULT_EXP_MULTIPLIER,
        max=_DEFAULT_MAX_DELAY_SECONDS,
    )(retry_state)


def async_vendor_retry(
    *,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    base_delay_seconds: float = _DEFAULT_BASE_DELAY_SECONDS,
    max_delay_seconds: float = _DEFAULT_MAX_DELAY_SECONDS,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Build a tenacity-based async retry decorator with vendor-friendly defaults.

    Returned decorator wraps an async function. Each call is independent —
    no shared state across invocations.
    """

    def _wait(retry_state: RetryCallState) -> float:
        hint = _retry_after_seconds(retry_state)
        if hint is not None:
            return min(hint, max_delay_seconds)
        return wait_exponential(multiplier=base_delay_seconds, max=max_delay_seconds)(retry_state)

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(max_attempts),
                wait=_wait,
                retry=retry_if_exception(_should_retry),
                reraise=True,
            ):
                with attempt:
                    return await fn(*args, **kwargs)
            # AsyncRetrying always either returns or raises; this line keeps
            # pyright's control-flow analysis happy.
            raise RuntimeError("AsyncRetrying exited without returning")

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        return wrapper

    return decorator


# Re-export for tests that want to assert on the wait helper directly.
__all__ = ["_combined_wait", "_should_retry", "async_vendor_retry"]
