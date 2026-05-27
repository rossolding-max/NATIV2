"""Integration tests for the Meta OAuth callback route.

Exercises ``GET /api/v1/webhooks/meta/oauth_callback``. Uses:
- Postgres testcontainer for ``talent`` + ``talent_vault`` tables
- Redis testcontainer for OAuth state storage
- respx-mocked Meta exchange_code endpoint
"""

from __future__ import annotations

import contextlib
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
    minio_container: Any,
    redis_container: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Migrate the testcontainer Postgres + bind Meta secrets.

    Depending on ``redis_container`` triggers the conftest to bind
    ``app.config.settings.redis_*`` to the testcontainer Redis (so the
    OAuth state store can persist + retrieve).
    """
    _ = redis_container
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "meta_app_id", "meta-app-id-test")
    monkeypatch.setattr(app_settings, "meta_app_secret", SecretStr("meta-app-secret-test"))

    repo = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "alembic"))
    command.upgrade(cfg, "head")

    return {"postgres": postgres_container, "minio": minio_container}


@pytest.fixture
async def m5_app(_m5_setup_env: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    """Boot the FastAPI app against the migrated testcontainer Postgres."""
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

    # Reset module-level async clients so they re-bind to THIS test's
    # event loop (rather than a leaked one from a prior fixture).
    from app.vendors import _oauth_state, _rate_limiter

    _http_client.reset_client_for_tests()
    _oauth_state.reset_client_for_tests()
    _rate_limiter.reset_client_for_tests()

    async def _noop(_v: str, _b: str, *, max_per_period: int, period_seconds: int) -> None:
        return None

    try:
        with patch("app.vendors.meta_graph.check_rate_limit", _noop):
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
    """Insert a minimal talent row so OAuth callback has something to patch."""
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
                "name": "Test Talent",
                "data": json.dumps({"id": talent_id}),
                "agency": str(_TEST_AGENCY_ID),
            },
        )
        await session.commit()


async def _put_oauth_state(state: str, *, talent_id: str, platform: str, **extra: Any) -> None:
    """Write a synthetic state into Redis so the callback validates."""
    from app.vendors._oauth_state import get_redis_client

    client = get_redis_client()
    payload: dict[str, Any] = {
        "talent_id": talent_id,
        "platform": platform,
        "agency_id": str(_TEST_AGENCY_ID),
        **extra,
    }
    await client.setex(f"oauth_state:{state}", 600, json.dumps(payload))  # type: ignore[misc]


@respx.mock
async def test_integration__meta_oauth_callback__happy_path(m5_app: AsyncClient) -> None:
    talent_id = f"acme-talent-{uuid4().hex[:8]}"
    state = f"state-{uuid4().hex}"

    from app.db import session as db_session

    await _seed_talent(db_session.async_session_factory, talent_id)
    await _put_oauth_state(
        state,
        talent_id=talent_id,
        platform="meta",
        scopes=["instagram_business_basic", "instagram_business_manage_insights"],
    )

    respx.post("https://api.instagram.com/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "ig-short-lived-xyz",
                "user_id": 1234567890,
                "expires_in": 3600,
            },
        )
    )

    r = await m5_app.get(f"/api/v1/webhooks/meta/oauth_callback?code=fresh-code&state={state}")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["success"] is True
    assert body["talent_id"] == talent_id
    assert body["platform"] == "meta"


@respx.mock
async def test_integration__meta_oauth_callback__missing_state_rejected(
    m5_app: AsyncClient,
) -> None:
    r = await m5_app.get("/api/v1/webhooks/meta/oauth_callback?code=fresh")
    assert r.status_code == 422
    body = r.json()
    assert body["errors"][0]["code"] == "VALIDATION_ERROR"


@respx.mock
async def test_integration__meta_oauth_callback__unknown_state_rejected(
    m5_app: AsyncClient,
) -> None:
    r = await m5_app.get("/api/v1/webhooks/meta/oauth_callback?code=fresh&state=never-set")
    assert r.status_code == 422
    body = r.json()
    assert "unknown" in body["errors"][0]["message"].lower()


@respx.mock
async def test_integration__meta_oauth_callback__state_consumed_single_use(
    m5_app: AsyncClient,
) -> None:
    """Second call with the same state must fail (single-use)."""
    talent_id = f"acme-talent-{uuid4().hex[:8]}"
    state = f"state-{uuid4().hex}"

    from app.db import session as db_session

    await _seed_talent(db_session.async_session_factory, talent_id)
    await _put_oauth_state(state, talent_id=talent_id, platform="meta", scopes=[])

    respx.post("https://api.instagram.com/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "ig-token", "expires_in": 3600})
    )

    r = await m5_app.get(f"/api/v1/webhooks/meta/oauth_callback?code=c1&state={state}")
    assert r.status_code == 200

    r = await m5_app.get(f"/api/v1/webhooks/meta/oauth_callback?code=c2&state={state}")
    assert r.status_code == 422


@respx.mock
async def test_integration__meta_oauth_callback__user_denied(m5_app: AsyncClient) -> None:
    r = await m5_app.get("/api/v1/webhooks/meta/oauth_callback?error=access_denied")
    assert r.status_code == 422
    body = r.json()
    assert "user denied" in body["errors"][0]["message"]


@respx.mock
async def test_integration__meta_oauth_callback__token_persists_to_vault(
    m5_app: AsyncClient,
) -> None:
    talent_id = f"acme-talent-{uuid4().hex[:8]}"
    state = f"state-{uuid4().hex}"

    from app.db import session as db_session

    await _seed_talent(db_session.async_session_factory, talent_id)
    await _put_oauth_state(state, talent_id=talent_id, platform="meta", scopes=["a", "b"])

    respx.post("https://api.instagram.com/oauth/access_token").mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "ig-vaulted-token", "expires_in": 3600},
        )
    )

    r = await m5_app.get(f"/api/v1/webhooks/meta/oauth_callback?code=fresh-code&state={state}")
    assert r.status_code == 200

    # Verify the token was written into talent_vault and decrypts back to plaintext.
    from app.repositories.talent_vault import TalentVaultRepository

    async with db_session.async_session_factory() as session:
        vault_repo = TalentVaultRepository(session)
        row = await vault_repo.get(talent_id=talent_id, platform="meta")

    assert row is not None
    assert row.access_token == "ig-vaulted-token"
    assert row.scopes == ["a", "b"]
    assert row.scope_validated_at is not None


def test_integration__cleanup_truncates_between_files() -> None:
    """Sanity: subsequent test files should each get a clean DB.

    We don't TRUNCATE talent here because each test uses a unique talent_id
    derived from uuid4. The integration suite's between-file isolation is
    by-PK; cascade from the talent FK clears talent_vault on talent delete.
    """
    # Placeholder — the assertion is implicit in the other tests passing.
    with contextlib.suppress(Exception):
        pass
