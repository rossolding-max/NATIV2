"""M8 Phase 3a brand-contacts REST surface integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from alembic import command

_SENTINEL_AGENCY_ID = UUID(int=0)
_TEST_TALENT_ID = "m8-test-talent"
_TEST_BRAND_ID = "m8-test-brand"


@pytest.fixture
def _m8_setup_env(  # pyright: ignore[reportUnusedFunction]
    postgres_container: Any,
    minio_container: Any,
    redis_container: Any,
) -> Any:
    _ = redis_container
    _ = minio_container
    repo = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


@pytest.fixture
async def m8_app(_m8_setup_env: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings
    from app.db import session as db_session

    new_engine = create_async_engine(live_settings.database_url_async, future=True)
    new_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    original_engine = db_session.engine
    original_factory = db_session.async_session_factory
    db_session.engine = new_engine
    db_session.async_session_factory = new_factory

    async with new_factory() as s:
        await s.execute(
            text(
                "TRUNCATE TABLE brand_contact, brand_candidate, brand_deal, "
                "talent_vault, talent, brand, agency_profile, memo CASCADE"
            )
        )
        await s.execute(
            text(
                "INSERT INTO talent (talent_id, name, status, data, agency_id, "
                "created_at, updated_at, is_deleted) "
                "VALUES (:tid, :name, 'onboarding', :data, :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "tid": _TEST_TALENT_ID,
                "name": "M8 Talent",
                "data": json.dumps({"id": _TEST_TALENT_ID}),
                "agency": str(_SENTINEL_AGENCY_ID),
            },
        )
        await s.execute(
            text(
                "INSERT INTO brand (brand_id, name, industry_id, domain, data, "
                "created_at, updated_at, is_deleted) "
                "VALUES (:bid, :name, :iid, :domain, '{}', "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE) "
                "ON CONFLICT (brand_id) DO NOTHING"
            ),
            {
                "bid": _TEST_BRAND_ID,
                "name": "M8 Brand",
                "iid": "activewear",
                "domain": "m8brand.com",
            },
        )
        await s.commit()

    try:
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


async def _seed_contact(
    db_factory: Any,
    *,
    brand_id: str = _TEST_BRAND_ID,
    decision_role: str = "buyer",
    do_not_contact: bool = False,
) -> str:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings

    _ = db_factory  # unused — re-create a connection to avoid session reuse
    engine = create_async_engine(live_settings.database_url_async, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    contact_id = f"bc_test_{uuid4().hex[:8]}"
    async with factory() as s:
        from app.repositories.brand_contact import BrandContactRepository

        repo = BrandContactRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        await repo.upsert_run_batch(
            brand_id,
            [
                {
                    "contact_id": contact_id,
                    "name": "Test Contact",
                    "decision_role": decision_role,
                    "title": "VP Marketing",
                    "seniority": "vp",
                    "email": {"address": "test@brand.com", "verification_status": "verified"},
                    "do_not_contact": do_not_contact,
                    "qualification": {
                        "score": 0.7,
                        "tier": "qualified",
                        "signals": [],
                    },
                }
            ],
            agency_id=_SENTINEL_AGENCY_ID,
        )
        await s.commit()
    await engine.dispose()
    return contact_id


async def test_integration__list_brand_contacts__happy_path(m8_app: AsyncClient) -> None:
    await _seed_contact(None, decision_role="buyer")
    await _seed_contact(None, decision_role="influencer")
    r = await m8_app.get(f"/api/v1/brands/{_TEST_BRAND_ID}/contacts")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == 2
    decision_roles = {row["decision_role"] for row in data}
    assert decision_roles == {"buyer", "influencer"}


async def test_integration__list_brand_contacts__filter_by_decision_role(
    m8_app: AsyncClient,
) -> None:
    await _seed_contact(None, decision_role="buyer")
    await _seed_contact(None, decision_role="influencer")
    r = await m8_app.get(f"/api/v1/brands/{_TEST_BRAND_ID}/contacts?decision_role=buyer")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["decision_role"] == "buyer"


async def test_integration__get_brand_contact_by_id(m8_app: AsyncClient) -> None:
    contact_id = await _seed_contact(None)
    r = await m8_app.get(f"/api/v1/brand-contacts/{contact_id}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["contact_id"] == contact_id


async def test_integration__get_contact__missing_404(m8_app: AsyncClient) -> None:
    r = await m8_app.get("/api/v1/brand-contacts/bc_does_not_exist")
    assert r.status_code == 404


async def test_integration__patch_workflow_state(m8_app: AsyncClient) -> None:
    contact_id = await _seed_contact(None)
    r = await m8_app.patch(
        f"/api/v1/brand-contacts/{contact_id}",
        json={
            "do_not_contact": True,
            "do_not_contact_reason": "opted out via reply",
            "tags": ["unsubscribed"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["do_not_contact"] is True
    assert body["data"]["do_not_contact_reason"] == "opted out via reply"
    assert body["data"]["tags"] == ["unsubscribed"]


async def test_integration__pitchable_excludes_dnc(m8_app: AsyncClient) -> None:
    _ok = await _seed_contact(None, decision_role="buyer", do_not_contact=False)
    _dnc = await _seed_contact(None, decision_role="influencer", do_not_contact=True)
    r = await m8_app.get(
        f"/api/v1/talents/{_TEST_TALENT_ID}/pitchable-contacts?brand_id={_TEST_BRAND_ID}"
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == 1  # the DNC contact filtered out
    assert data[0]["do_not_contact"] is False


async def test_integration__pitchable__missing_talent_404(m8_app: AsyncClient) -> None:
    r = await m8_app.get(
        f"/api/v1/talents/no-such-talent/pitchable-contacts?brand_id={_TEST_BRAND_ID}"
    )
    assert r.status_code == 404


async def test_integration__trigger_enrichment_run_202(m8_app: AsyncClient) -> None:
    """Manual trigger enqueues the Celery task and returns 202."""
    with patch("app.celery_app.app.send_task", return_value=None) as mock_send:
        r = await m8_app.post(
            f"/api/v1/brands/{_TEST_BRAND_ID}/contact-enrichment/run",
            json={"talent_id": _TEST_TALENT_ID, "target_titles": ["VP Marketing"]},
        )
    assert r.status_code == 202, r.text
    body = r.json()["data"]
    assert body["enqueued"] is True
    assert body["brand_id"] == _TEST_BRAND_ID
    mock_send.assert_called_once()
    sent_args = mock_send.call_args.kwargs.get("args")
    assert sent_args is not None
    assert sent_args[0] == _TEST_BRAND_ID
    assert sent_args[2] == _TEST_TALENT_ID
    assert sent_args[3] == ["VP Marketing"]


async def test_integration__trigger_run__no_body_uses_defaults(m8_app: AsyncClient) -> None:
    """POST with no body still works — runs full pipeline with default target_titles."""
    with patch("app.celery_app.app.send_task", return_value=None) as mock_send:
        r = await m8_app.post(f"/api/v1/brands/{_TEST_BRAND_ID}/contact-enrichment/run")
    assert r.status_code == 202, r.text
    sent_args = mock_send.call_args.kwargs.get("args")
    assert sent_args is not None
    assert sent_args[2] is None  # talent_id
    assert sent_args[3] is None  # target_titles


async def test_integration__trigger_run__missing_brand_404(m8_app: AsyncClient) -> None:
    r = await m8_app.post(
        "/api/v1/brands/no-such-brand/contact-enrichment/run",
        json={},
    )
    assert r.status_code == 404


async def test_integration__trigger_run__bad_talent_id_404(m8_app: AsyncClient) -> None:
    r = await m8_app.post(
        f"/api/v1/brands/{_TEST_BRAND_ID}/contact-enrichment/run",
        json={"talent_id": "no-such-talent"},
    )
    assert r.status_code == 404
