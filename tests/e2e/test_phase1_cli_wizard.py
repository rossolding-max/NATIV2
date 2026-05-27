"""E2E: Phase 1 talent-onboarding CLI wizard driven against the in-process API.

Uses the same testcontainer (Postgres + Redis + MinIO) fixtures the happy-path
integration test uses, then invokes ``app.cli.phase1_onboarding.run_wizard``
with a sync ``httpx.Client`` bound to an in-process ASGI transport. ``--auto``
+ ``--skip-oauth`` + ``--skip-activate`` keeps it deterministic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from pydantic import SecretStr

from alembic import command


@pytest.fixture
def _m5_setup_env(  # pyright: ignore[reportUnusedFunction]
    postgres_container: Any,
    minio_container: Any,
    redis_container: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Migrate Postgres + bind Meta/TikTok secrets + create MinIO bucket."""
    _ = redis_container
    _ = minio_container

    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "meta_app_id", "meta-app-id-test")
    monkeypatch.setattr(app_settings, "meta_app_secret", SecretStr("meta-app-secret-test"))
    monkeypatch.setattr(app_settings, "tiktok_client_key", "tt-client-key-test")
    monkeypatch.setattr(app_settings, "tiktok_client_secret", SecretStr("tt-client-secret-test"))

    repo = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "alembic"))
    command.upgrade(cfg, "head")

    from app.utils import s3 as s3_util

    s3_util.reset_client_for_tests()
    import contextlib

    s3_client = s3_util.get_s3_client()
    with contextlib.suppress(Exception):
        s3_client.create_bucket(Bucket=app_settings.s3_bucket)
    return postgres_container


@pytest.mark.usefixtures("_m5_setup_env")
def test_e2e__phase1_wizard_auto_mode_walks_full_flow() -> None:
    """Wizard's ``--auto --skip-oauth --skip-activate`` completes without raising."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from starlette.testclient import TestClient as StarletteTestClient

    from app.cli.phase1_onboarding import run_wizard
    from app.config import settings as live_settings
    from app.db import session as db_session
    from app.main import app
    from app.vendors import _http_client, _oauth_state, _rate_limiter

    new_engine = create_async_engine(live_settings.database_url_async, future=True)
    new_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    original_engine = db_session.engine
    original_factory = db_session.async_session_factory
    db_session.engine = new_engine
    db_session.async_session_factory = new_factory

    _http_client.reset_client_for_tests()
    _oauth_state.reset_client_for_tests()
    _rate_limiter.reset_client_for_tests()

    try:
        with StarletteTestClient(app) as starlette_client:
            # The wizard expects an ``httpx.Client``-shaped interface
            # (.get/.post/.patch/.put). StarletteTestClient already exposes
            # exactly that, plus context-manager methods, so we wrap it in
            # a tiny proxy and pass it directly to ``run_wizard(client=...)``.
            proxy = _StarletteToHttpxProxy(starlette_client)
            final = run_wizard(
                api_base_url="http://testserver",
                auto=True,
                skip_oauth=True,
                skip_activate=True,
                talent_name="Wizard Talent",
                client=proxy,  # type: ignore[arg-type]
            )
    finally:
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(new_engine.dispose())
        finally:
            loop.close()
        db_session.engine = original_engine
        db_session.async_session_factory = original_factory

    assert final["status"] in {"onboarding", "active"}
    assert final["data"].get("contract_template", {}).get("based_on_starter_template_id")


class _StarletteToHttpxProxy:
    """Thin shim so the wizard can call .get/.post/.patch on a TestClient."""

    def __init__(self, starlette_client: Any) -> None:
        self._client = starlette_client

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._client.get(path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._client.post(path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self._client.patch(path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self._client.put(path, **kwargs)
