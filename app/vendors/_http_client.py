"""Shared ``httpx.AsyncClient`` singleton for all vendor wrappers.

Mirrors the lazy-init pattern used in ``app/agents/llm_client.py`` for
``AsyncAnthropic``. Reuses one connection pool across every vendor call to
avoid per-request handshake overhead under Celery.

Closed implicitly on process exit. Tests reset via ``reset_client_for_tests``.
"""

from __future__ import annotations

import httpx

_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0
_DEFAULT_POOL_MAX_KEEPALIVE = 20
_DEFAULT_POOL_MAX_CONNECTIONS = 100

_client: httpx.AsyncClient | None = None


def get_async_http_client() -> httpx.AsyncClient:
    """Return the lazy-initialised shared ``httpx.AsyncClient`` singleton."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                _DEFAULT_TIMEOUT_SECONDS,
                connect=_DEFAULT_CONNECT_TIMEOUT_SECONDS,
            ),
            limits=httpx.Limits(
                max_keepalive_connections=_DEFAULT_POOL_MAX_KEEPALIVE,
                max_connections=_DEFAULT_POOL_MAX_CONNECTIONS,
            ),
            follow_redirects=False,
        )
    return _client


def reset_client_for_tests() -> None:
    """Reset the singleton (test-only helper)."""
    global _client
    _client = None
