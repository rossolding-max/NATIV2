"""End-to-end Phase 0 setup happy path test.

Drives the 9-step setup via the REST surface against:
- Real Postgres (testcontainer; migrations applied)
- Real MinIO (testcontainer; bucket created)
- respx-mocked Smartlead (DNS endpoints + email account create/warmup)
- patched dns.asyncresolver (returns SPF + DKIM + DMARC TXT)

Confirms the final agency_profile row passes schema validation with
``status == "active"``.
"""

from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from pydantic import AnyHttpUrl, SecretStr

from alembic import command

_TEST_BUCKET = "m4-happy-path-bucket"


def _fake_txt_answer(value: str) -> Any:
    rr = MagicMock()
    rr.strings = (value.encode("utf-8"),)
    return [rr]


@pytest.fixture
def _m4_setup_env(  # pyright: ignore[reportUnusedFunction]
    postgres_container: Any,
    minio_container: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Sync fixture — points env + settings at the testcontainers + migrates.

    Migration runs in a sync context because Alembic's ``env.py`` calls
    ``asyncio.run(...)``, which conflicts with an outer running loop.
    """
    url = postgres_container.get_connection_url().replace("+psycopg2", "")
    match = re.match(
        r"postgresql(?:\+\w+)?://(?P<user>[^:]+):(?P<pw>[^@]+)@(?P<host>[^:]+):(?P<port>\d+)/(?P<db>.+)",
        url,
    )
    assert match is not None
    monkeypatch.setenv("POSTGRES_USER", match["user"])
    monkeypatch.setenv("POSTGRES_PASSWORD", match["pw"])
    monkeypatch.setenv("POSTGRES_HOST", match["host"])
    monkeypatch.setenv("POSTGRES_PORT", match["port"])
    monkeypatch.setenv("POSTGRES_DB", match["db"])
    monkeypatch.setenv("DB_MASTER_KEY", "test-master-key-32-bytes-base64==")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-stub")

    minio_cfg = minio_container.get_config()
    minio_endpoint = f"http://{minio_cfg['endpoint']}"

    # Lazy import so app.config isn't loaded at module collection time —
    # that would freeze settings to default env, breaking downstream tests.
    from app.config import get_settings
    from app.config import settings as app_settings

    get_settings.cache_clear()
    monkeypatch.setattr(app_settings, "s3_endpoint_url", AnyHttpUrl(minio_endpoint))
    monkeypatch.setattr(app_settings, "s3_access_key", minio_cfg["access_key"])
    monkeypatch.setattr(app_settings, "s3_secret_key", SecretStr(minio_cfg["secret_key"]))
    monkeypatch.setattr(app_settings, "s3_bucket", _TEST_BUCKET)
    monkeypatch.setattr(app_settings, "s3_force_path_style", True)
    monkeypatch.setattr(app_settings, "smartlead_api_key", SecretStr("sk-smartlead-test"))
    # POSTGRES_* env vars are already monkeypatched. Re-bind the module-level
    # ``settings`` so app.db.session sees the testcontainer URL on next import.
    monkeypatch.setattr(app_settings, "postgres_host", os.environ["POSTGRES_HOST"])
    monkeypatch.setattr(app_settings, "postgres_port", int(os.environ["POSTGRES_PORT"]))
    monkeypatch.setattr(app_settings, "postgres_db", os.environ["POSTGRES_DB"])
    monkeypatch.setattr(app_settings, "postgres_user", os.environ["POSTGRES_USER"])
    monkeypatch.setattr(
        app_settings, "postgres_password", SecretStr(os.environ["POSTGRES_PASSWORD"])
    )

    # Migrate (sync — uses asyncio.run internally).
    repo = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "alembic"))
    command.upgrade(cfg, "head")

    # Pre-create MinIO bucket.
    from app.utils import s3 as s3_util

    s3_util.reset_client_for_tests()
    s3_client = s3_util.get_s3_client()
    with contextlib.suppress(Exception):
        s3_client.create_bucket(Bucket=_TEST_BUCKET)

    return {"postgres": postgres_container, "minio": minio_container}


@pytest.fixture
async def m4_app(_m4_setup_env: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    """Boot the FastAPI app against the migrated testcontainer; yield AsyncClient."""
    # Rebuild the async engine + session factory against the rebound settings.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings
    from app.db import session as db_session
    from app.utils import s3 as s3_util
    from app.vendors import _http_client

    new_engine = create_async_engine(live_settings.database_url_async, future=True)
    new_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    # Patch the module-level engine + session factory so app.main + endpoints use it.
    original_engine = db_session.engine
    original_factory = db_session.async_session_factory
    db_session.engine = new_engine
    db_session.async_session_factory = new_factory

    _http_client.reset_client_for_tests()

    async def _noop(_v: str, _b: str, *, max_per_period: int, period_seconds: int) -> None:
        return None

    try:
        with patch("app.vendors.smartlead.check_rate_limit", _noop):
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
        s3_util.reset_client_for_tests()


@respx.mock
async def test_e2e__phase_0_happy_path__ends_in_active_status(m4_app: AsyncClient) -> None:
    # Smartlead create email_account
    respx.post("https://server.smartlead.ai/api/v1/email-accounts/save").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "data": {"id": 42, "is_smtp_success": True, "is_imap_success": True},
            },
        )
    )

    # Patch DNS resolver to return verified records.
    from app.services import dns_validation as dnsv

    async def _resolve(name: Any, _rdtype: Any) -> Any:
        name_str = str(name)
        if name_str == "acme.com":
            return _fake_txt_answer("v=spf1 include:_spf.smartlead.ai ~all")
        if name_str == "smartlead._domainkey.acme.com":
            return _fake_txt_answer("v=DKIM1; p=MIIB...")
        if name_str == "_dmarc.acme.com":
            return _fake_txt_answer("v=DMARC1; p=none")
        raise RuntimeError(f"unexpected dns lookup: {name_str}")

    with patch.object(dnsv, "_build_resolver") as mock_resolver_factory:
        resolver = MagicMock()
        resolver.resolve = AsyncMock(side_effect=_resolve)
        mock_resolver_factory.return_value = resolver

        # 1. POST /agencies (Step 1)
        r = await m4_app.post(
            "/api/v1/agencies",
            json={
                "agency_slug": "acme",
                "name": "Acme Talent",
                "domain": "acme.com",
                "website_url": "https://acme.com",
                "company_address": "1 Main St, City",
            },
        )
        assert r.status_code == 201, r.text

        # 1.5 PATCH branding
        r = await m4_app.patch(
            "/api/v1/agencies/me/branding",
            json={"primary_color": "#0F4C81", "background_color": "#FFFFFF"},
        )
        assert r.status_code == 200, r.text

        # 2. PATCH agent
        r = await m4_app.patch(
            "/api/v1/agencies/me/agent",
            json={"agent_id": "sarah", "name": "Sarah Chen", "email": "sarah@acme.com"},
        )
        assert r.status_code == 200, r.text

        # 3. POST /dns/refresh
        r = await m4_app.post(
            "/api/v1/agencies/me/dns/refresh", json={"dkim_selector": "smartlead"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["verified"] is True

        # 4. POST /mailbox
        r = await m4_app.post(
            "/api/v1/agencies/me/mailbox",
            json={
                "agent_id": "sarah",
                "mailbox_address": "sarah@acme.com",
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 465,
                "smtp_username": "sarah@acme.com",
                "smtp_password": "app-pw",
                "imap_host": "imap.gmail.com",
                "imap_port": 993,
                "daily_send_cap": 50,
            },
        )
        assert r.status_code == 200, r.text

        # 5. PATCH signature
        r = await m4_app.patch(
            "/api/v1/agencies/me/signature",
            json={
                "default_signature_template": (
                    "{agent_name}\n{agency_address}\nUnsubscribe: {unsubscribe_link}"
                )
            },
        )
        assert r.status_code == 200, r.text

        # 5.5 PATCH invoice-template
        r = await m4_app.patch(
            "/api/v1/agencies/me/invoice-template",
            json={
                "tax_handling": "none",
                "default_payment_terms_days": 30,
                "invoice_footer": "Thank you.",
                "payment_instructions_markdown": "Bank: ...",
            },
        )
        assert r.status_code == 200, r.text

        # 5.5b PATCH commission-defaults
        r = await m4_app.patch(
            "/api/v1/agencies/me/commission-defaults",
            json={
                "default_commission_rate": 0.20,
                "default_commission_model": "agency_invoices_brand_pays_talent_net",
            },
        )
        assert r.status_code == 200, r.text

        # 6. Simulate warmup complete: directly bump the JSONB value (in
        # real life this happens via the Celery task in PR 3).
        # We use PATCH branding as a way to also patch sending_mailboxes
        # via the same code path — but branding doesn't accept it. So
        # call the DNS refresh again to keep things consistent then bump
        # mailbox via a special test-only path: hit the DB directly.
        from sqlalchemy import text

        # Pick up the patched module-level session factory (the fixture
        # replaced it with one bound to the testcontainer Postgres).
        from app.db import session as db_session

        async with db_session.async_session_factory() as session:
            await session.execute(
                text(
                    "UPDATE agency_profile SET data = jsonb_set("
                    "data, '{sending_mailboxes,0,warmup_status}', '\"complete\"'::jsonb)"
                )
            )
            await session.commit()

        # 7. POST /activate
        r = await m4_app.post("/api/v1/agencies/me/activate")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "active"

        # Final GET
        r = await m4_app.get("/api/v1/agencies/me")
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["status"] == "active"
        assert body["data"]["domain"] == "acme.com"
        assert body["data"]["sending_mailboxes"][0]["warmup_status"] == "complete"
