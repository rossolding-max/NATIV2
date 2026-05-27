"""CSRF state management + OAuth authorize-URL builders.

OAuth flows are vulnerable to CSRF if the callback accepts any `state`
value: the attacker initiates a flow on their account, gets the platform
to redirect the victim through, and the victim's session ends up bound to
the attacker's tokens. To prevent this we:

1. Generate a cryptographically-random ``state`` per flow.
2. Store it in Redis DB 2 (the same DB used by the rate limiter) with a
   short TTL (default 10 min) along with the (talent_id, platform) it
   refers to. For TikTok we also store the PKCE ``code_verifier`` so the
   callback can complete the exchange.
3. On callback, atomically validate + consume the state. Single-use.

Per CLAUDE.md: never read ``os.environ``. Settings come from
``app.config.settings``.

M3 ships the helpers only — M5 (talent onboarding) wires them into FastAPI
callback routes.
"""

from __future__ import annotations

import json
import secrets
from typing import Any
from urllib.parse import urlencode

import redis.asyncio as aioredis

from app.config import settings

_DEFAULT_TTL_SECONDS = 600
_STATE_KEY_PREFIX = "oauth_state:"

_redis_client: aioredis.Redis | None = None


def get_redis_client() -> aioredis.Redis:
    """Lazy-init async Redis client bound to the rate-limit / state DB."""
    global _redis_client
    if _redis_client is None:
        kwargs: dict[str, object] = {
            "host": settings.redis_host,
            "port": settings.redis_port,
            "db": settings.redis_db_ratelimit,
            "decode_responses": True,
        }
        if settings.redis_password is not None:
            kwargs["password"] = settings.redis_password.get_secret_value()
        _redis_client = aioredis.Redis(**kwargs)  # type: ignore[arg-type]
    return _redis_client


def reset_client_for_tests() -> None:
    """Reset the Redis singleton (test-only)."""
    global _redis_client
    _redis_client = None


def generate_state(nbytes: int = 32) -> str:
    """Return a URL-safe random string suitable for an OAuth ``state``."""
    return secrets.token_urlsafe(nbytes)


async def store_state(
    state: str,
    *,
    talent_id: str,
    platform: str,
    code_verifier: str | None = None,
    ttl_seconds: int = _DEFAULT_TTL_SECONDS,
) -> None:
    """Persist the binding between ``state`` and (talent_id, platform).

    ``code_verifier`` is stored alongside the state for PKCE flows
    (TikTok). The callback retrieves it to complete the token exchange.
    """
    payload = json.dumps(
        {"talent_id": talent_id, "platform": platform, "code_verifier": code_verifier}
    )
    client = get_redis_client()
    await client.setex(f"{_STATE_KEY_PREFIX}{state}", ttl_seconds, payload)  # type: ignore[misc]


async def validate_and_consume_state(state: str) -> dict[str, Any] | None:
    """Atomically GET + DEL the state binding. Single-use.

    Returns the stored payload or ``None`` if missing/expired.
    """
    client = get_redis_client()
    key = f"{_STATE_KEY_PREFIX}{state}"
    # Pipeline so GET + DEL are sent as a single round-trip; the DEL
    # always runs even if GET returns nil.
    pipe = client.pipeline(transaction=True)
    pipe.get(key)
    pipe.delete(key)
    results = await pipe.execute()  # type: ignore[misc]
    raw_value: str | None = results[0]
    if raw_value is None:
        return None
    parsed: dict[str, Any] = json.loads(raw_value)
    return parsed


def build_authorize_url(
    *,
    base_url: str,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    state: str,
    response_type: str = "code",
    extra: dict[str, str] | None = None,
) -> str:
    """Compose an OAuth authorize URL with a ``scope=`` separator of choice.

    Meta uses comma-separated scopes; TikTok uses comma-separated too;
    standard OAuth uses spaces. Callers pass an already-joined string via
    ``scopes`` or this helper joins with spaces by default.
    """
    params: dict[str, str] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": response_type,
        "state": state,
        "scope": " ".join(scopes),
    }
    if extra is not None:
        params.update(extra)
    return f"{base_url.rstrip('/')}?{urlencode(params)}"
