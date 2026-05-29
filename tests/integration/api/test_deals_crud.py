"""M10 Phase 4 deal REST surface integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from alembic import command

_SENTINEL_AGENCY_ID = UUID(int=0)
_TALENT_ID = "m10-test-talent"
_BRAND_ID = "m10-test-brand"
_CONTACT_ID = "bc_m10_test"


@pytest.fixture
def _m10_setup_env(  # pyright: ignore[reportUnusedFunction]
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
async def m10_app(_m10_setup_env: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
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
                "tid": _TALENT_ID,
                "name": "M10 Talent",
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
                "name": "M10 Brand",
                "iid": "activewear",
                "domain": "m10brand.com",
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
                "cid": _CONTACT_ID,
                "bid": _BRAND_ID,
                "name": "M10 Contact",
                "email": "contact@m10brand.com",
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


async def _create_deal(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {
        "talent_id": _TALENT_ID,
        "brand_id": _BRAND_ID,
        "primary_contact_id": _CONTACT_ID,
        "by_agent_id": "agent_alice",
    }
    body.update(overrides)
    r = await client.post("/api/v1/deals", json=body)
    assert r.status_code == 201, r.text
    return r.json()["data"]


# ── manual creation ─────────────────────────────────────────────────


async def test_integration__create_deal_lands_in_lead_new_lead(m10_app: AsyncClient) -> None:
    body = await _create_deal(m10_app)
    assert body["stage"] == "lead"
    assert body["substage"] == "new_lead"
    assert body["is_terminal"] is False
    assert body["is_won"] is False
    history = body["data"]["stage_history"]
    assert len(history) == 1
    assert history[0]["substage"] == "new_lead"


# ── list endpoints ──────────────────────────────────────────────────


async def test_integration__list_deals_by_talent_returns_all_non_terminal(
    m10_app: AsyncClient,
) -> None:
    await _create_deal(m10_app)
    await _create_deal(m10_app)
    r = await m10_app.get(f"/api/v1/talents/{_TALENT_ID}/deals")
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 2


async def test_integration__list_deals_by_brand_returns_all_non_terminal(
    m10_app: AsyncClient,
) -> None:
    await _create_deal(m10_app)
    r = await m10_app.get(f"/api/v1/brands/{_BRAND_ID}/deals")
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 1


async def test_integration__list_deals_filter_by_stage(m10_app: AsyncClient) -> None:
    await _create_deal(m10_app)
    r = await m10_app.get(f"/api/v1/talents/{_TALENT_ID}/deals?stage=lead")
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) == 1
    r2 = await m10_app.get(f"/api/v1/talents/{_TALENT_ID}/deals?stage=proposal")
    assert r2.status_code == 200
    assert r2.json()["data"] == []


# ── get + 404 ───────────────────────────────────────────────────────


async def test_integration__get_deal_by_id(m10_app: AsyncClient) -> None:
    body = await _create_deal(m10_app)
    r = await m10_app.get(f"/api/v1/deals/{body['deal_id']}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["deal_id"] == body["deal_id"]


async def test_integration__get_deal_missing_404(m10_app: AsyncClient) -> None:
    r = await m10_app.get("/api/v1/deals/deal_missing")
    assert r.status_code == 404


# ── patch — happy + guard rails ─────────────────────────────────────


async def test_integration__patch_deal_user_notes(m10_app: AsyncClient) -> None:
    body = await _create_deal(m10_app)
    r = await m10_app.patch(
        f"/api/v1/deals/{body['deal_id']}",
        json={"data": {"user_notes": "called with brand contact"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["data"]["user_notes"] == "called with brand contact"


async def test_integration__patch_deal_campaign_hashtags_tier1_g2(
    m10_app: AsyncClient,
) -> None:
    """Tier-1 G2 fix: ``data.delivery.campaign_hashtags`` is writable via PATCH."""
    body = await _create_deal(m10_app)
    r = await m10_app.patch(
        f"/api/v1/deals/{body['deal_id']}",
        json={"data": {"delivery": {"campaign_hashtags": ["#FitStar", "#PartnerAd"]}}},
    )
    assert r.status_code == 200, r.text
    tags = r.json()["data"]["data"]["delivery"]["campaign_hashtags"]
    assert tags == ["#FitStar", "#PartnerAd"]


async def test_integration__patch_deal_refuses_direct_substage_write(
    m10_app: AsyncClient,
) -> None:
    body = await _create_deal(m10_app)
    r = await m10_app.patch(
        f"/api/v1/deals/{body['deal_id']}",
        json={"substage": "qualified"},
    )
    assert r.status_code == 422
    assert "transition" in r.text


async def test_integration__patch_deal_refuses_direct_stage_write(
    m10_app: AsyncClient,
) -> None:
    body = await _create_deal(m10_app)
    r = await m10_app.patch(
        f"/api/v1/deals/{body['deal_id']}",
        json={"stage": "proposal"},
    )
    assert r.status_code == 422


async def test_integration__patch_deal_refuses_data_loss_block(
    m10_app: AsyncClient,
) -> None:
    body = await _create_deal(m10_app)
    r = await m10_app.patch(
        f"/api/v1/deals/{body['deal_id']}",
        json={"data": {"loss": {"reason": "budget"}}},
    )
    assert r.status_code == 422
    assert "/loss" in r.text


# ── transition endpoint ─────────────────────────────────────────────


async def test_integration__transition_lead_to_initial_call_scheduled(
    m10_app: AsyncClient,
) -> None:
    body = await _create_deal(m10_app)
    r = await m10_app.post(
        f"/api/v1/deals/{body['deal_id']}/transition",
        json={"target_substage": "initial_call_scheduled", "by_agent_id": "agent_alice"},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["deal"]["substage"] == "initial_call_scheduled"
    assert len(data["chain"]) == 1
    assert data["chain"][0]["is_auto_advance"] is False


async def test_integration__transition_qualified_auto_advances_to_proposal_drafting(
    m10_app: AsyncClient,
) -> None:
    """Locked decision (2): ``qualified`` auto-advances to PROPOSAL."""
    body = await _create_deal(m10_app)
    # Walk to ``initial_call_completed`` first.
    for target in ("initial_call_scheduled", "initial_call_completed"):
        r = await m10_app.post(
            f"/api/v1/deals/{body['deal_id']}/transition",
            json={"target_substage": target, "by_agent_id": "agent_alice"},
        )
        assert r.status_code == 200, r.text
    # Now ``qualified`` — should chain to ``proposal_drafting``.
    r = await m10_app.post(
        f"/api/v1/deals/{body['deal_id']}/transition",
        json={"target_substage": "qualified", "by_agent_id": "agent_alice"},
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["deal"]["stage"] == "proposal"
    assert data["deal"]["substage"] == "proposal_drafting"
    chain = data["chain"]
    assert len(chain) == 2
    assert chain[0]["substage"] == "qualified"
    assert chain[0]["by_agent_id"] == "agent_alice"
    assert chain[0]["is_auto_advance"] is False
    assert chain[1]["substage"] == "proposal_drafting"
    assert chain[1]["by_agent_id"] == "system"
    assert chain[1]["is_auto_advance"] is True


async def test_integration__transition_invalid_returns_422(m10_app: AsyncClient) -> None:
    body = await _create_deal(m10_app)
    r = await m10_app.post(
        f"/api/v1/deals/{body['deal_id']}/transition",
        json={"target_substage": "contract_drafting"},  # not allowed from new_lead
    )
    assert r.status_code == 422


async def test_integration__transition_missing_deal_404(m10_app: AsyncClient) -> None:
    r = await m10_app.post(
        "/api/v1/deals/deal_missing/transition",
        json={"target_substage": "initial_call_scheduled"},
    )
    assert r.status_code == 404


# ── loss endpoint ───────────────────────────────────────────────────


async def test_integration__loss_endpoint_writes_structured_block(
    m10_app: AsyncClient,
) -> None:
    body = await _create_deal(m10_app)
    r = await m10_app.post(
        f"/api/v1/deals/{body['deal_id']}/loss",
        json={
            "reason": "budget",
            "competitor_brand": "Gymshark",
            "notes": "out of FY budget",
            "by_agent_id": "agent_alice",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["deal"]["substage"] == "lost"
    assert data["deal"]["is_terminal"] is True
    assert data["deal"]["is_won"] is False
    loss = data["loss"]
    assert loss["reason"] == "budget"
    assert loss["lost_at_stage"] == "lead"
    assert loss["competitor_brand"] == "Gymshark"


async def test_integration__loss_invalid_reason_returns_422(m10_app: AsyncClient) -> None:
    body = await _create_deal(m10_app)
    r = await m10_app.post(
        f"/api/v1/deals/{body['deal_id']}/loss",
        json={"reason": "not_a_valid_reason"},
    )
    assert r.status_code == 422, r.text
    assert "invalid loss reason" in r.text


# ── stage-history endpoint ─────────────────────────────────────────


async def test_integration__stage_history_endpoint_returns_audit_log(
    m10_app: AsyncClient,
) -> None:
    body = await _create_deal(m10_app)
    await m10_app.post(
        f"/api/v1/deals/{body['deal_id']}/transition",
        json={"target_substage": "initial_call_scheduled"},
    )
    r = await m10_app.get(f"/api/v1/deals/{body['deal_id']}/stage-history")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["substage"] == "initial_call_scheduled"
    history = data["history"]
    assert len(history) == 2
    assert history[0]["substage"] == "new_lead"
    assert history[1]["substage"] == "initial_call_scheduled"


# ── due-for-action endpoint ─────────────────────────────────────────


async def test_integration__due_for_action_returns_overdue_deals(
    m10_app: AsyncClient,
) -> None:
    body = await _create_deal(m10_app)
    # Set next_action_due_at to the past.
    await m10_app.patch(
        f"/api/v1/deals/{body['deal_id']}",
        json={"next_action_due_at": "2020-01-01T00:00:00+00:00"},
    )
    r = await m10_app.get("/api/v1/deals/due-for-action")
    assert r.status_code == 200, r.text
    assert any(d["deal_id"] == body["deal_id"] for d in r.json()["data"])


async def test_integration__due_for_action_filtered_by_talent(
    m10_app: AsyncClient,
) -> None:
    body = await _create_deal(m10_app)
    await m10_app.patch(
        f"/api/v1/deals/{body['deal_id']}",
        json={"next_action_due_at": "2020-01-01T00:00:00+00:00"},
    )
    r = await m10_app.get(f"/api/v1/deals/due-for-action?talent_id={_TALENT_ID}")
    assert r.status_code == 200, r.text
    assert len(r.json()["data"]) >= 1
    r2 = await m10_app.get("/api/v1/deals/due-for-action?talent_id=no-such-talent")
    assert r2.status_code == 200
    assert r2.json()["data"] == []
