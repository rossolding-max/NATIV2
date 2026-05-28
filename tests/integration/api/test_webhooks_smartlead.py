"""M9 Smartlead webhook receivers — signature verify + 6 event types + dedupe + reply→deal."""

from __future__ import annotations

import hashlib
import hmac
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
from app.services.outreach.reply_classifier import OutcomeClassification

_SENTINEL_AGENCY_ID = UUID(int=0)
_TEST_TALENT_ID = "m9-test-talent"
_TEST_BRAND_ID = "m9-test-brand"
_TEST_CONTACT_ID = "bc_m9_test"
_TEST_WEBHOOK_SECRET = "test-webhook-secret-for-m9"


@pytest.fixture
def _m9_setup_env(  # pyright: ignore[reportUnusedFunction]
    postgres_container: Any,
    minio_container: Any,
    redis_container: Any,
    monkeypatch: Any,
) -> Any:
    _ = redis_container
    _ = minio_container
    # Patch settings.smartlead_webhook_secret BEFORE any settings.* read.
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "smartlead_webhook_secret", SecretStr(_TEST_WEBHOOK_SECRET))
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
                "do_not_contact, data, agency_id, created_at, updated_at, is_deleted) "
                "VALUES (:cid, :bid, :name, 'buyer', FALSE, '{}', :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "cid": _TEST_CONTACT_ID,
                "bid": _TEST_BRAND_ID,
                "name": "Test Contact",
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


async def _seed_enrollment(state: str = "active") -> str:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings
    from app.repositories.pitch_enrollment import PitchEnrollmentRepository

    engine = create_async_engine(live_settings.database_url_async, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    eid = f"enr_{uuid4().hex[:12]}"
    async with factory() as s:
        repo = PitchEnrollmentRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        await repo.insert_draft(
            enrollment_id=eid,
            talent_id=_TEST_TALENT_ID,
            contact_id=_TEST_CONTACT_ID,
            brand_id=_TEST_BRAND_ID,
            template_id="buyer-direct-pitch",
            agency_id=_SENTINEL_AGENCY_ID,
            data={"steps": [{"step_number": 1, "subject": "S", "body": "B"}]},
        )
        if state != "awaiting_approval":
            await repo.set_state(eid, state)
        await s.commit()
    await engine.dispose()
    return eid


def _sign(body: bytes) -> str:
    return hmac.new(_TEST_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


async def test_integration__email_event__missing_signature_401(m9_app: AsyncClient) -> None:
    r = await m9_app.post(
        "/api/v1/webhooks/smartlead/email_event",
        content=b"{}",
    )
    assert r.status_code in {401, 403}


async def test_integration__email_event__bad_signature_401(m9_app: AsyncClient) -> None:
    body = json.dumps({}).encode()
    r = await m9_app.post(
        "/api/v1/webhooks/smartlead/email_event",
        content=body,
        headers={"X-Smartlead-Signature": "deadbeef", "Content-Type": "application/json"},
    )
    assert r.status_code in {401, 403}


async def test_integration__email_event__opened_records_event(m9_app: AsyncClient) -> None:
    eid = await _seed_enrollment()
    body = json.dumps(
        {
            "event_type": "email_opened",
            "campaign_id": "C1",
            "lead_id": "L1",
            "occurred_at": "2026-05-28T16:00:00Z",
            "seq_number": 1,
            "custom_fields": {"enrollment_id": eid},
        }
    ).encode()
    r = await m9_app.post(
        "/api/v1/webhooks/smartlead/email_event",
        content=body,
        headers={"X-Smartlead-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["data"]["status"] == "processed"


async def test_integration__email_event__duplicate_event_short_circuits(
    m9_app: AsyncClient,
) -> None:
    eid = await _seed_enrollment()
    payload = {
        "event_type": "email_opened",
        "campaign_id": "C1",
        "lead_id": "L1",
        "occurred_at": "2026-05-28T16:00:00Z",
        "seq_number": 1,
        "custom_fields": {"enrollment_id": eid},
    }
    body = json.dumps(payload).encode()
    headers = {
        "X-Smartlead-Signature": _sign(body),
        "Content-Type": "application/json",
    }
    r1 = await m9_app.post("/api/v1/webhooks/smartlead/email_event", content=body, headers=headers)
    r2 = await m9_app.post("/api/v1/webhooks/smartlead/email_event", content=body, headers=headers)
    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r2.json()["data"]["status"] == "duplicate"


async def test_integration__email_event__bounce_kills_enrollment(m9_app: AsyncClient) -> None:
    eid = await _seed_enrollment()
    body = json.dumps(
        {
            "event_type": "email_bounced",
            "campaign_id": "C1",
            "lead_id": "L1",
            "occurred_at": "2026-05-28T16:00:00Z",
            "custom_fields": {"enrollment_id": eid},
        }
    ).encode()
    r = await m9_app.post(
        "/api/v1/webhooks/smartlead/email_event",
        content=body,
        headers={"X-Smartlead-Signature": _sign(body), "Content-Type": "application/json"},
    )
    assert r.status_code == 202, r.text
    # Verify the enrollment is now killed.
    g = await m9_app.get(f"/api/v1/enrollments/{eid}")
    assert g.json()["data"]["state"] == "killed"


async def test_integration__reply__interested_creates_deal(m9_app: AsyncClient) -> None:
    eid = await _seed_enrollment()
    classification = OutcomeClassification(
        outcome="interested",
        confidence=0.9,
        rationale="wants a call",
        extracted_signals={"asked_for_meeting": True},
    )
    body = json.dumps(
        {
            "event_type": "email_replied",
            "campaign_id": "C1",
            "lead_id": "L1",
            "occurred_at": "2026-05-28T16:00:00Z",
            "custom_fields": {"enrollment_id": eid},
            "reply_body": "Sounds great, free Tuesday?",
        }
    ).encode()

    with patch(
        "app.services.outreach.reply_classifier.classify_reply",
        AsyncMock(return_value=classification),
    ):
        r = await m9_app.post(
            "/api/v1/webhooks/smartlead/reply",
            content=body,
            headers={
                "X-Smartlead-Signature": _sign(body),
                "Content-Type": "application/json",
            },
        )
    assert r.status_code == 202, r.text
    body_out = r.json()["data"]
    assert body_out["outcome"] == "interested"
    assert "deal_id" in body_out
    assert body_out["next_state"] == "completed"

    # Verify bidirectional FK landed on both sides.
    enr_after = await m9_app.get(f"/api/v1/enrollments/{eid}")
    assert enr_after.json()["data"]["state"] == "completed"
    assert enr_after.json()["data"]["created_deal_id"] == body_out["deal_id"]
