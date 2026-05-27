"""Step 2 — platform OAuth flow orchestration.

The agency UI (or the CLI wizard) calls ``start_oauth_flow`` which:

1. Generates a CSRF state token.
2. Stores the state payload in Redis DB 2 with a 10-min TTL — the payload
   carries ``talent_id``, ``platform``, ``redirect_uri``, ``agency_id``
   plus a PKCE ``code_verifier`` for TikTok.
3. Returns the platform's authorize URL for the UI to redirect to.

The callback at ``/api/v1/webhooks/{platform}/oauth_callback`` (shipped in
Commit 1) consumes the state, exchanges the code for a token, persists
into ``talent_vault``, and mirrors the connection state into
``talent.data.platforms[N].api_credentials``.

YouTube + Twitch + LinkedIn-OAuth + Pinterest + Snap deferred per M5
locked decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.errors import ValidationError
from app.vendors._oauth_state import generate_state, store_state
from app.vendors.meta_graph import MetaGraphClient
from app.vendors.tiktok import TikTokClient, generate_pkce_pair

SUPPORTED_PLATFORMS: frozenset[str] = frozenset({"meta", "tiktok"})


@dataclass(frozen=True)
class OAuthStartResult:
    """Return shape for ``start_oauth_flow`` — the UI redirects to ``authorize_url``."""

    authorize_url: str
    state: str
    platform: str


async def start_oauth_flow(
    *,
    talent_id: str,
    platform: str,
    redirect_uri: str,
    scopes: list[str] | None = None,
    agency_id: Any = None,
    state_ttl_seconds: int = 600,
) -> OAuthStartResult:
    """Generate the authorize URL + persist the state in Redis."""
    if platform not in SUPPORTED_PLATFORMS:
        raise ValidationError(
            f"platform {platform!r} not supported in v0.1 "
            f"(supported: {sorted(SUPPORTED_PLATFORMS)})",
            field="platform",
        )

    state = generate_state()
    state_payload: dict[str, Any] = {
        "talent_id": talent_id,
        "platform": platform,
        "redirect_uri": redirect_uri,
        "scopes": scopes or [],
    }
    if agency_id is not None:
        state_payload["agency_id"] = str(agency_id)

    if platform == "meta":
        client = MetaGraphClient()
        authorize_url = client.build_authorize_url(
            redirect_uri=redirect_uri,
            state=state,
            scopes=scopes,
        )
    else:  # tiktok
        verifier, challenge = generate_pkce_pair()
        state_payload["code_verifier"] = verifier
        tiktok_client = TikTokClient()
        authorize_url = tiktok_client.build_authorize_url(
            redirect_uri=redirect_uri,
            state=state,
            code_challenge=challenge,
            scopes=scopes,
        )

    # Write the richer state payload directly (carrying agency_id +
    # scopes + redirect_uri in addition to the talent_id + platform +
    # code_verifier that _oauth_state.store_state would write). The key
    # prefix matches _oauth_state's internal namespace so
    # ``validate_and_consume_state`` can find it.
    import json as _json

    from app.vendors._oauth_state import get_redis_client

    redis_client = get_redis_client()
    await redis_client.setex(  # type: ignore[misc]
        f"oauth_state:{state}", state_ttl_seconds, _json.dumps(state_payload)
    )
    # Reference store_state so it remains in the public import surface;
    # M5+ may consolidate to use it as the canonical writer.
    _ = store_state

    return OAuthStartResult(authorize_url=authorize_url, state=state, platform=platform)
