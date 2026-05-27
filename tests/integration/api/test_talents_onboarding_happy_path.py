"""End-to-end Phase 1 talent onboarding happy path against testcontainers.

Drives the REST router through the 10 steps. Smartlead / Meta / TikTok
HTTP traffic is respx-mocked; Postgres + Redis + MinIO are testcontainers.

The full ``/activate`` cross-field guard rejects an incomplete profile,
so we have to patch enough of the talent.data shape to satisfy the
schema + activation guard before flipping to ``active``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import respx
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
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

    repo = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "alembic"))
    command.upgrade(cfg, "head")

    # Pre-create the MinIO bucket the presigned-URL endpoint will reference.
    from app.utils import s3 as s3_util

    s3_util.reset_client_for_tests()
    import contextlib

    s3_client = s3_util.get_s3_client()
    with contextlib.suppress(Exception):
        s3_client.create_bucket(Bucket=app_settings.s3_bucket)

    return postgres_container


@pytest.fixture
async def m5_app(_m5_setup_env: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    """FastAPI ASGI client bound to the testcontainer Postgres."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings
    from app.db import session as db_session
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

    async def _noop(_v: str, _b: str, *, max_per_period: int, period_seconds: int) -> None:
        return None

    try:
        with (
            patch("app.vendors.meta_graph.check_rate_limit", _noop),
            patch("app.vendors.tiktok.check_rate_limit", _noop),
        ):
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


@respx.mock
async def test_e2e__phase_1_happy_path__ends_in_active_status(m5_app: AsyncClient) -> None:
    # Step 1 — create the talent draft.
    r = await m5_app.post(
        "/api/v1/talents",
        json={
            "name": "Jane Doe",
            "country": "US",
            "initial_platform_handle": "@janedoe",
            "initial_platform_name": "instagram",
            "content_niches": ["beauty", "lifestyle"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()["data"]
    talent_id = body["talent_id"]
    assert body["status"] == "onboarding"
    assert body["data"]["disclosure_defaults"]["style"] == "#ad"

    # Step 2 — request the Meta OAuth start URL (we don't drive the
    # callback in this test; the dedicated OAuth tests cover that).
    r = await m5_app.post(
        f"/api/v1/talents/{talent_id}/platforms/start-oauth",
        json={
            "platform": "meta",
            "redirect_uri": "https://app.example.com/oauth/meta",
            "scopes": ["instagram_business_basic"],
        },
    )
    assert r.status_code == 200, r.text
    assert "instagram.com/oauth/authorize" in r.json()["data"]["authorize_url"]

    # Step 5 — fetch a question (any).
    r = await m5_app.post(f"/api/v1/talents/{talent_id}/questionnaire/next")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["complete"] is False

    # Step 5b — answer a couple of questions via the questionnaire endpoint.
    for path, value in [
        ("pronouns", "she/her"),
        ("contact.email", "jane@doe.com"),
        ("billing_entity.legal_name", "Jane Doe Co."),
        ("billing_entity.country", "US"),
    ]:
        r = await m5_app.post(
            f"/api/v1/talents/{talent_id}/questionnaire/answer",
            json={"field_path": path, "value": value},
        )
        assert r.status_code == 200, r.text

    # Step 6 — resolve industry for a brand.
    r = await m5_app.post(
        f"/api/v1/talents/{talent_id}/brands/resolve-industry",
        json={"brand_name": "Unknown Brand XYZ"},
    )
    assert r.status_code == 200, r.text
    inference = r.json()["data"]
    assert inference["source"] in {"exact_match", "unknown"}

    # Step 7 — add a similar-talent manual seed.
    r = await m5_app.post(
        f"/api/v1/talents/{talent_id}/similar-talent",
        json={"name": "Other Creator", "handles": ["@other"]},
    )
    assert r.status_code == 200, r.text

    # Step 7.5 — adopt a starter contract template.
    r = await m5_app.post(
        f"/api/v1/talents/{talent_id}/contract-template/adopt-starter",
        json={"starter_slug": "management"},
    )
    assert r.status_code == 200, r.text

    # Step 7.5b — material edit bumps version.
    r = await m5_app.patch(
        f"/api/v1/talents/{talent_id}/contract-template",
        json={"default_governing_law": "California"},
    )
    assert r.status_code == 200, r.text
    new_template = r.json()["data"]["data"]["contract_template"]
    assert new_template["template_version"] == "0.1.1"

    # Step 8 — attempt /activate; should fail (no scope_validated_at yet
    # because OAuth callback not driven, no previous_brands either).
    r = await m5_app.post(f"/api/v1/talents/{talent_id}/activate")
    assert r.status_code in (409, 422), r.text  # BusinessRuleError or ValidationError

    # Simulate the OAuth + reconciliation outcome by patching directly
    # via the questionnaire/patch endpoint with the activation guard's
    # minimum: a platform with scope_validated_at + billing legal_name
    # (already set) + previous_brands with industry_id.
    from app.db import session as db_session
    from app.repositories.talent import TalentRepository
    from app.services.talent_onboarding import TalentOnboardingService

    async with db_session.async_session_factory() as session:
        repo = TalentRepository(session, agency_id=None)
        await repo.patch_data(
            talent_id,
            {
                "platforms": [
                    {
                        "platform": "instagram",
                        "handle": "@janedoe",
                        "api_credentials": {
                            "access_token_ref": f"vault:talent_{talent_id}:meta",
                            "scopes": ["instagram_business_basic"],
                            "scope_validated_at": "2026-05-27T00:00:00+00:00",
                        },
                    }
                ],
                "previous_brands": [{"brand": "Acme", "industry_id": "consumer-electronics"}],
            },
        )
        await session.commit()

    # Stub the celery send_task so /activate doesn't try to connect to broker.
    with patch("app.celery_app.app.send_task", return_value=None):
        r = await m5_app.post(f"/api/v1/talents/{talent_id}/activate")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == "active"

    # Final GET confirms persisted state.
    r = await m5_app.get(f"/api/v1/talents/{talent_id}")
    body = r.json()["data"]
    assert body["status"] == "active"
    assert body["data"]["billing_entity"]["legal_name"] == "Jane Doe Co."
    assert body["data"]["contract_template"]["template_version"] == "0.1.1"
    _ = TalentOnboardingService  # imported for completeness
