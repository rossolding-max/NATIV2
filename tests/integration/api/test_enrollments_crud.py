"""M9 enrollment REST surface integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from alembic import command

_SENTINEL_AGENCY_ID = UUID(int=0)
_TEST_TALENT_ID = "m9-test-talent"
_TEST_BRAND_ID = "m9-test-brand"
_TEST_CONTACT_ID = "bc_m9_test"


@pytest.fixture
def _m9_setup_env(  # pyright: ignore[reportUnusedFunction]
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
async def m9_app(_m9_setup_env: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
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
                "TRUNCATE TABLE pitch_enrollment, brand_contact, brand_candidate, "
                "brand_deal, talent_vault, talent, brand, agency_profile, "
                "memo, deal CASCADE"
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
                "tid": _TEST_TALENT_ID,
                "name": "M9 Talent",
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
                "name": "M9 Brand",
                "iid": "activewear",
                "domain": "m9brand.com",
            },
        )
        await s.execute(
            text(
                "INSERT INTO brand_contact (contact_id, brand_id, name, decision_role, "
                "email, do_not_contact, data, agency_id, created_at, updated_at, is_deleted) "
                "VALUES (:cid, :bid, :name, 'buyer', "
                "pgp_sym_encrypt(:email, current_setting('app.master_key', true)), "
                "FALSE, '{}', :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "cid": _TEST_CONTACT_ID,
                "bid": _TEST_BRAND_ID,
                "name": "Test Contact",
                "email": "contact@m9brand.com",
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


async def _seed_enrollment(
    *,
    enrollment_id: str | None = None,
    state: str = "awaiting_approval",
    template_id: str = "buyer-direct-pitch",
) -> str:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings
    from app.repositories.pitch_enrollment import PitchEnrollmentRepository

    engine = create_async_engine(live_settings.database_url_async, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    enrollment_id = enrollment_id or f"enr_{uuid4().hex[:12]}"
    async with factory() as s:
        repo = PitchEnrollmentRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        await repo.insert_draft(
            enrollment_id=enrollment_id,
            talent_id=_TEST_TALENT_ID,
            contact_id=_TEST_CONTACT_ID,
            brand_id=_TEST_BRAND_ID,
            template_id=template_id,
            agency_id=_SENTINEL_AGENCY_ID,
            data={
                "steps": [
                    {
                        "step_number": 1,
                        "subject": "S",
                        "body": "B",
                        "timing_offset_days": 0,
                        "angles_used": {"primary": "comp_proof"},
                    }
                ]
            },
        )
        if state != "awaiting_approval":
            await repo.set_state(enrollment_id, state)
        await s.commit()
    await engine.dispose()
    return enrollment_id


async def test_integration__list_enrollments_by_talent(m9_app: AsyncClient) -> None:
    await _seed_enrollment()
    await _seed_enrollment()
    r = await m9_app.get(f"/api/v1/talents/{_TEST_TALENT_ID}/enrollments")
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 2


async def test_integration__list_enrollments_filter_by_state(m9_app: AsyncClient) -> None:
    await _seed_enrollment(state="awaiting_approval")
    eid = await _seed_enrollment(state="active")
    r = await m9_app.get(f"/api/v1/talents/{_TEST_TALENT_ID}/enrollments?state=active")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["enrollment_id"] == eid


async def test_integration__get_enrollment_by_id(m9_app: AsyncClient) -> None:
    eid = await _seed_enrollment()
    r = await m9_app.get(f"/api/v1/enrollments/{eid}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["enrollment_id"] == eid


async def test_integration__get_enrollment_missing_404(m9_app: AsyncClient) -> None:
    r = await m9_app.get("/api/v1/enrollments/enr_missing")
    assert r.status_code == 404


async def test_integration__patch_enrollment_workflow_state(m9_app: AsyncClient) -> None:
    eid = await _seed_enrollment()
    r = await m9_app.patch(
        f"/api/v1/enrollments/{eid}",
        json={"user_notes": "saw the reply manually"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["data"]["user_notes"] == "saw the reply manually"


async def test_integration__kill_enrollment(m9_app: AsyncClient) -> None:
    eid = await _seed_enrollment(state="active")
    r = await m9_app.post(
        f"/api/v1/enrollments/{eid}/kill",
        json={"reason": "manual_kill_test"},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["state"] == "killed"
    assert body["data"]["kill_reason"] == "manual_kill_test"


async def test_integration__approve_enrollment_pushes_to_smartlead(
    m9_app: AsyncClient,
) -> None:
    eid = await _seed_enrollment(state="awaiting_approval")
    fake_meta = {
        "campaign_id": "smartlead_C42",
        "lead_id": "L99",
        "campaign_name": f"{_TEST_TALENT_ID}::buyer-direct-pitch",
    }
    with patch(
        "app.services.outreach.smartlead_push.push_to_smartlead",
        AsyncMock(return_value=fake_meta),
    ) as mock_push:
        r = await m9_app.post(f"/api/v1/enrollments/{eid}/approve")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["state"] == "active"
    assert body["data"]["smartlead_meta"] == fake_meta
    assert body["data"]["approved_at"] is not None
    mock_push.assert_awaited_once()


async def test_integration__approve_wrong_state_rejected(m9_app: AsyncClient) -> None:
    eid = await _seed_enrollment(state="active")
    r = await m9_app.post(f"/api/v1/enrollments/{eid}/approve")
    assert r.status_code == 422


async def test_integration__trigger_outreach_generation_enqueues(
    m9_app: AsyncClient,
) -> None:
    with patch("app.celery_app.app.send_task", return_value=None) as mock_send:
        r = await m9_app.post(
            f"/api/v1/talents/{_TEST_TALENT_ID}/outreach-generation/run",
            json={"contact_id": _TEST_CONTACT_ID, "brand_id": _TEST_BRAND_ID},
        )
    assert r.status_code == 202, r.text
    body = r.json()["data"]
    assert body["enqueued"] is True
    sent_args = mock_send.call_args.kwargs.get("args")
    assert sent_args is not None
    assert sent_args[0] == _TEST_TALENT_ID
    assert sent_args[1] == _TEST_CONTACT_ID
    assert sent_args[2] == _TEST_BRAND_ID


async def test_integration__trigger_outreach_missing_talent_404(m9_app: AsyncClient) -> None:
    r = await m9_app.post(
        "/api/v1/talents/no-such/outreach-generation/run",
        json={"contact_id": _TEST_CONTACT_ID, "brand_id": _TEST_BRAND_ID},
    )
    assert r.status_code == 404


async def test_integration__list_enrollments_by_brand(m9_app: AsyncClient) -> None:
    await _seed_enrollment()
    r = await m9_app.get(f"/api/v1/brands/{_TEST_BRAND_ID}/enrollments")
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) >= 1
