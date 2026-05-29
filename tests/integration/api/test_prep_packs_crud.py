"""M11 Discovery Prep Pack REST integration tests."""

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
_TALENT_ID = "m11-test-talent"
_BRAND_ID = "m11-test-brand"
_CONTACT_ID = "bc_m11_test"


@pytest.fixture
def _m11_setup_env(  # pyright: ignore[reportUnusedFunction]
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
async def m11_app(_m11_setup_env: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
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
                "TRUNCATE TABLE discovery_prep_pack, pitch_enrollment, brand_contact, "
                "brand_candidate, brand_deal, talent_vault, talent, brand, "
                "agency_profile, memo, deal CASCADE"
            )
        )
        await s.execute(
            text(
                "INSERT INTO talent (talent_id, name, status, data, agency_id, "
                "created_at, updated_at, is_deleted) "
                "VALUES (:tid, :name, 'active', :data, :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "tid": _TALENT_ID,
                "name": "M11 Talent",
                "data": json.dumps({"id": _TALENT_ID}),
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
                "bid": _BRAND_ID,
                "name": "M11 Brand",
                "iid": "activewear",
                "domain": "m11brand.com",
            },
        )
        await s.execute(
            text(
                "INSERT INTO brand_contact (contact_id, brand_id, name, decision_role, "
                "email, do_not_contact, data, agency_id, created_at, updated_at, "
                "is_deleted) "
                "VALUES (:cid, :bid, :name, 'buyer', "
                "pgp_sym_encrypt(:email, current_setting('app.master_key', true)), "
                "FALSE, '{}', :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "cid": _CONTACT_ID,
                "bid": _BRAND_ID,
                "name": "M11 Contact",
                "email": "contact@m11brand.com",
                "agency": str(_SENTINEL_AGENCY_ID),
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


async def _create_deal(client: AsyncClient, substage: str = "initial_call_scheduled") -> str:
    """Manual create lands the deal at lead/new_lead; transition it onward."""
    r = await client.post(
        "/api/v1/deals",
        json={
            "talent_id": _TALENT_ID,
            "brand_id": _BRAND_ID,
            "primary_contact_id": _CONTACT_ID,
            "by_agent_id": "agent_test",
        },
    )
    assert r.status_code == 201, r.text
    deal_id = r.json()["data"]["deal_id"]
    if substage != "new_lead":
        # Walk to the requested substage.
        r2 = await client.post(
            f"/api/v1/deals/{deal_id}/transition",
            json={"target_substage": "initial_call_scheduled"},
        )
        assert r2.status_code == 200, r2.text
        if substage != "initial_call_scheduled":
            r3 = await client.post(
                f"/api/v1/deals/{deal_id}/transition",
                json={"target_substage": substage},
            )
            assert r3.status_code == 200, r3.text
    return deal_id


async def _seed_pack(deal_id: str, *, version: int = 1, is_latest: bool = True) -> str:
    """Seed a discovery_prep_pack row directly so GET endpoints have data."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings

    engine = create_async_engine(live_settings.database_url_async, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    prep_pack_id = f"prep_{uuid4().hex[:10]}_v{version}"
    async with factory() as s:
        await s.execute(
            text(
                "INSERT INTO discovery_prep_pack ("
                "prep_pack_id, deal_id, version, is_latest, status, data, "
                "agency_id, created_at, updated_at, is_deleted) "
                "VALUES (:pid, :did, :v, :is_latest, 'completed', :data, :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "pid": prep_pack_id,
                "did": deal_id,
                "v": version,
                "is_latest": is_latest,
                "data": json.dumps(
                    {
                        "generation": {"trigger": "auto_on_initial_call_scheduled"},
                        "briefing_notes": {"deal_summary": "test"},
                    }
                ),
                "agency": str(_SENTINEL_AGENCY_ID),
            },
        )
        if is_latest:
            await s.execute(
                text("UPDATE deal SET latest_prep_pack_id = :pid WHERE deal_id = :did"),
                {"pid": prep_pack_id, "did": deal_id},
            )
        await s.commit()
    await engine.dispose()
    return prep_pack_id


# ── GET endpoints ───────────────────────────────────────────────────


async def test_integration__get_latest_prep_pack_404_when_none(
    m11_app: AsyncClient,
) -> None:
    deal_id = await _create_deal(m11_app)
    r = await m11_app.get(f"/api/v1/deals/{deal_id}/prep-pack")
    assert r.status_code == 404


async def test_integration__get_latest_prep_pack_returns_pack(
    m11_app: AsyncClient,
) -> None:
    deal_id = await _create_deal(m11_app)
    pid = await _seed_pack(deal_id, version=1)
    r = await m11_app.get(f"/api/v1/deals/{deal_id}/prep-pack")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["prep_pack_id"] == pid
    assert data["version"] == 1
    assert data["is_latest"] is True
    assert data["data"]["briefing_notes"]["deal_summary"] == "test"


async def test_integration__list_versions_returns_summary_per_version(
    m11_app: AsyncClient,
) -> None:
    deal_id = await _create_deal(m11_app)
    await _seed_pack(deal_id, version=1, is_latest=False)
    await _seed_pack(deal_id, version=2, is_latest=True)
    r = await m11_app.get(f"/api/v1/deals/{deal_id}/prep-pack/versions")
    assert r.status_code == 200, r.text
    versions = r.json()["data"]
    assert len(versions) == 2
    assert versions[0]["version"] == 1
    assert versions[0]["is_latest"] is False
    assert versions[1]["version"] == 2
    assert versions[1]["is_latest"] is True
    # Trigger is surfaced from data.generation.trigger.
    assert versions[1]["trigger"] == "auto_on_initial_call_scheduled"


# ── POST /generate ──────────────────────────────────────────────────


async def test_integration__generate_happy_path_enqueues_task(
    m11_app: AsyncClient,
) -> None:
    deal_id = await _create_deal(m11_app)
    with patch("app.celery_app.app.send_task", return_value=None) as mock_send:
        r = await m11_app.post(
            f"/api/v1/deals/{deal_id}/prep-pack/generate",
            json={
                "pre_generation_guidance": "Lead with the case study",
                "by_agent_id": "agent_ross",
            },
        )
    assert r.status_code == 202, r.text
    body = r.json()["data"]
    assert body["enqueued"] is True
    assert body["pack_type"] == "discovery_prep"
    # Verify the dispatcher kwargs include the M11 guidance.
    kwargs = mock_send.call_args.kwargs["kwargs"]
    assert kwargs["pack_type"] == "discovery_prep"
    assert kwargs["pre_generation_guidance"] == "Lead with the case study"
    assert kwargs["agent_id"] == "agent_ross"


async def test_integration__generate_422_when_substage_wrong(
    m11_app: AsyncClient,
) -> None:
    deal_id = await _create_deal(m11_app, substage="new_lead")
    r = await m11_app.post(
        f"/api/v1/deals/{deal_id}/prep-pack/generate",
        json={"by_agent_id": "agent_ross"},
    )
    assert r.status_code == 422
    assert "initial_call_scheduled" in r.text


async def test_integration__generate_422_when_pack_already_exists(
    m11_app: AsyncClient,
) -> None:
    deal_id = await _create_deal(m11_app)
    await _seed_pack(deal_id, version=1)
    r = await m11_app.post(
        f"/api/v1/deals/{deal_id}/prep-pack/generate",
        json={"by_agent_id": "agent_ross"},
    )
    assert r.status_code == 422
    assert "regenerate" in r.text


async def test_integration__generate_missing_deal_404(m11_app: AsyncClient) -> None:
    r = await m11_app.post(
        "/api/v1/deals/deal_missing/prep-pack/generate",
        json={"by_agent_id": "agent_ross"},
    )
    assert r.status_code == 404


# ── POST /regenerate ────────────────────────────────────────────────


async def test_integration__regenerate_threads_parent_version(
    m11_app: AsyncClient,
) -> None:
    deal_id = await _create_deal(m11_app)
    await _seed_pack(deal_id, version=2, is_latest=True)
    with patch("app.celery_app.app.send_task", return_value=None) as mock_send:
        r = await m11_app.post(
            f"/api/v1/deals/{deal_id}/prep-pack/regenerate",
            json={
                "feedback": "Drop the sustainability angle; brand is performance-focused.",
                "by_agent_id": "agent_ross",
            },
        )
    assert r.status_code == 202, r.text
    body = r.json()["data"]
    assert body["enqueued"] is True
    assert body["parent_version"] == 2
    kwargs = mock_send.call_args.kwargs["kwargs"]
    assert kwargs["parent_version"] == 2
    assert kwargs["regeneration_feedback"].startswith("Drop the sustainability")


async def test_integration__regenerate_404_when_no_prior_pack(
    m11_app: AsyncClient,
) -> None:
    deal_id = await _create_deal(m11_app)
    r = await m11_app.post(
        f"/api/v1/deals/{deal_id}/prep-pack/regenerate",
        json={"feedback": "x", "by_agent_id": "agent_ross"},
    )
    assert r.status_code == 404
    assert "generate endpoint first" in r.text
