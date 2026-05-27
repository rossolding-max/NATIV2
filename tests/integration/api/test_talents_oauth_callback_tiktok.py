"""Integration tests for the TikTok OAuth callback route.

TikTok uses OAuth 2.0 with PKCE — the ``code_verifier`` was stored
alongside the state during ``start-oauth``. The callback retrieves it +
passes it to ``TikTokClient.exchange_code``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import pytest
import respx
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from alembic import command

_TEST_AGENCY_ID = UUID("00000000-0000-0000-0000-0000000000a5")


@pytest.fixture
def _m5_setup_env(  # pyright: ignore[reportUnusedFunction]
    postgres_container: Any,
    redis_container: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    _ = redis_container  # binding side effect via conftest
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "tiktok_client_key", "tt-client-key-test")
    monkeypatch.setattr(app_settings, "tiktok_client_secret", SecretStr("tt-client-secret-test"))

    repo = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


@pytest.fixture
async def m5_app(_m5_setup_env: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings
    from app.db import session as db_session
    from app.vendors import _http_client

    new_engine = create_async_engine(live_settings.database_url_async, future=True)
    new_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    original_engine = db_session.engine
    original_factory = db_session.async_session_factory
    db_session.engine = new_engine
    db_session.async_session_factory = new_factory

    from app.vendors import _oauth_state, _rate_limiter

    _http_client.reset_client_for_tests()
    _oauth_state.reset_client_for_tests()
    _rate_limiter.reset_client_for_tests()

    async def _noop(_v: str, _b: str, *, max_per_period: int, period_seconds: int) -> None:
        return None

    try:
        with patch("app.vendors.tiktok.check_rate_limit", _noop):
            from app.main import app

            async with (
                app.router.lifespan_context(app),
                AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
            ):
                yield client
    finally:
        await new_engine.dispose()
        db_session.engine = original_engine
        db_session.async_session_factory = original_factory


async def _seed_talent(db_session_factory: Any, talent_id: str) -> None:
    from sqlalchemy import text

    async with db_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO talent (talent_id, name, status, data, agency_id, "
                "created_at, updated_at, is_deleted) "
                "VALUES (:tid, :name, 'onboarding', :data, :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "tid": talent_id,
                "name": "TT Talent",
                "data": json.dumps({"id": talent_id}),
                "agency": str(_TEST_AGENCY_ID),
            },
        )
        await session.commit()


async def _put_oauth_state(
    state: str, *, talent_id: str, platform: str, code_verifier: str, **extra: Any
) -> None:
    from app.vendors._oauth_state import get_redis_client

    client = get_redis_client()
    payload: dict[str, Any] = {
        "talent_id": talent_id,
        "platform": platform,
        "code_verifier": code_verifier,
        "agency_id": str(_TEST_AGENCY_ID),
        **extra,
    }
    await client.setex(f"oauth_state:{state}", 600, json.dumps(payload))  # type: ignore[misc]


@respx.mock
async def test_integration__tiktok_oauth_callback__pkce_happy_path(
    m5_app: AsyncClient,
) -> None:
    talent_id = f"acme-talent-{uuid4().hex[:8]}"
    state = f"state-{uuid4().hex}"
    verifier = "test-verifier-128-chars"

    from app.db import session as db_session

    await _seed_talent(db_session.async_session_factory, talent_id)
    await _put_oauth_state(state, talent_id=talent_id, platform="tiktok", code_verifier=verifier)

    route = respx.post("https://open.tiktokapis.com/v2/oauth/token/").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "tt-access-xyz",
                "refresh_token": "tt-refresh-xyz",
                "expires_in": 86400,
                "scope": "user.info.basic,video.list",
            },
        )
    )

    r = await m5_app.get(f"/api/v1/webhooks/tiktok/oauth_callback?code=fresh-code&state={state}")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["success"] is True
    assert body["talent_id"] == talent_id
    assert body["platform"] == "tiktok"
    # Confirm the verifier was forwarded to TikTok.
    req_body = route.calls[0].request.content.decode()
    assert "code_verifier=test-verifier-128-chars" in req_body


@respx.mock
async def test_integration__tiktok_oauth_callback__missing_verifier_rejected(
    m5_app: AsyncClient,
) -> None:
    """State without ``code_verifier`` is a programming error → 422."""
    talent_id = f"acme-talent-{uuid4().hex[:8]}"
    state = f"state-{uuid4().hex}"

    from app.db import session as db_session
    from app.vendors._oauth_state import get_redis_client

    await _seed_talent(db_session.async_session_factory, talent_id)
    redis_client = get_redis_client()
    await redis_client.setex(  # type: ignore[misc]
        f"oauth_state:{state}", 600, json.dumps({"talent_id": talent_id, "platform": "tiktok"})
    )

    r = await m5_app.get(f"/api/v1/webhooks/tiktok/oauth_callback?code=fresh-code&state={state}")
    assert r.status_code == 422
    body = r.json()
    assert "code_verifier" in body["errors"][0]["message"]


@respx.mock
async def test_integration__tiktok_oauth_callback__token_persists_with_refresh(
    m5_app: AsyncClient,
) -> None:
    talent_id = f"acme-talent-{uuid4().hex[:8]}"
    state = f"state-{uuid4().hex}"

    from app.db import session as db_session

    await _seed_talent(db_session.async_session_factory, talent_id)
    await _put_oauth_state(
        state,
        talent_id=talent_id,
        platform="tiktok",
        code_verifier="verifier-X",
    )

    respx.post("https://open.tiktokapis.com/v2/oauth/token/").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "tt-stored",
                "refresh_token": "tt-rotate",
                "expires_in": 86400,
                "scope": "user.info.basic,video.list",
            },
        )
    )

    r = await m5_app.get(f"/api/v1/webhooks/tiktok/oauth_callback?code=c&state={state}")
    assert r.status_code == 200

    from app.repositories.talent_vault import TalentVaultRepository

    async with db_session.async_session_factory() as session:
        row = await TalentVaultRepository(session).get(talent_id=talent_id, platform="tiktok")

    assert row is not None
    assert row.access_token == "tt-stored"
    assert row.refresh_token == "tt-rotate"
    assert row.scopes == ["user.info.basic", "video.list"]
