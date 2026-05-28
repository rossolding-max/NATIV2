"""M6 — Phase 1.5 brand-deals REST surface integration tests.

Covers the 6 endpoints + honesty-floor rejection + auto-link to
``talent.data.previous_brands[]`` against testcontainer Postgres.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from alembic import command

_TODAY = datetime.now(UTC).date().isoformat()


@pytest.fixture
def _m6_setup_env(  # pyright: ignore[reportUnusedFunction]
    postgres_container: Any,
    minio_container: Any,
    redis_container: Any,
) -> Any:
    """Migrate Postgres + truncate tables we touch."""
    _ = redis_container
    _ = minio_container

    repo = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


@pytest.fixture
async def m6_app(_m6_setup_env: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    """FastAPI ASGI client bound to the testcontainer Postgres.

    Truncates brand_deal + talent_vault + talent + brand + agency_profile
    between tests so the lifespan-loaded singleton agency_id is clean.
    """
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
                "TRUNCATE TABLE brand_deal, talent_vault, talent, brand, "
                "agency_profile, memo CASCADE"
            )
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


async def _seed_talent(
    db_session_factory: Any,
    *,
    talent_id: str = "jane-doe",
    previous_brands: list[dict[str, Any]] | None = None,
) -> str:
    """Insert a minimal talent row. Picks up app.state.agency_id at lifespan."""
    import json as _json
    from uuid import UUID

    data = {"id": talent_id, "name": "Jane Doe"}
    if previous_brands is not None:
        data["previous_brands"] = previous_brands  # type: ignore[assignment]
    async with db_session_factory() as s:
        # Use whatever agency_id the lifespan would have loaded. Just use
        # a zero UUID — matches the TalentRepository sentinel when unbound.
        await s.execute(
            text(
                "INSERT INTO talent (talent_id, name, status, data, agency_id, "
                "created_at, updated_at, is_deleted) "
                "VALUES (:tid, :name, 'onboarding', :data, :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE) "
                "ON CONFLICT (talent_id) DO NOTHING"
            ),
            {
                "tid": talent_id,
                "name": "Jane Doe",
                "data": _json.dumps(data),
                "agency": str(UUID(int=0)),
            },
        )
        await s.commit()
    return talent_id


def _make_valid_deal_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "brand_name": "Gymshark",
        "industry_id": "activewear",
        "campaign_type": "sponsored_post",
        "outcome": "successful",
        "started_at": "2025-09-01",
        "ended_at": "2025-09-15",
        "fee_usd": 5000,
        "kpis": {
            "reach": {
                "value": 1_240_000,
                "source": "platform_verified",
                "as_of": _TODAY,
            }
        },
    }
    payload.update(overrides)
    return payload


# ── Happy path ───────────────────────────────────────────────────────


async def test_integration__create_brand_deal__happy_path(m6_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    await _seed_talent(async_session_factory)

    r = await m6_app.post("/api/v1/talents/jane-doe/brand-deals", json=_make_valid_deal_payload())
    assert r.status_code == 201, r.text
    body = r.json()["data"]
    assert body["talent_id"] == "jane-doe"
    assert body["brand_id"] == "gymshark"
    assert body["outcome"] == "successful"
    assert body["fee_usd"] == 5000
    assert body["brand_deal_id"].startswith("deal_2025_gymshark_")


async def test_integration__list_brand_deals__filters_by_outcome(m6_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    await _seed_talent(async_session_factory)
    await m6_app.post(
        "/api/v1/talents/jane-doe/brand-deals",
        json=_make_valid_deal_payload(outcome="successful"),
    )
    await m6_app.post(
        "/api/v1/talents/jane-doe/brand-deals",
        json=_make_valid_deal_payload(brand_name="Nike", outcome="underperformed"),
    )

    r_all = await m6_app.get("/api/v1/talents/jane-doe/brand-deals")
    assert r_all.status_code == 200
    assert len(r_all.json()["data"]) == 2

    r_filtered = await m6_app.get("/api/v1/talents/jane-doe/brand-deals?outcome=successful")
    assert r_filtered.status_code == 200
    rows = r_filtered.json()["data"]
    assert len(rows) == 1
    assert rows[0]["brand_id"] == "gymshark"


async def test_integration__get_brand_deal_by_id(m6_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    await _seed_talent(async_session_factory)
    created = await m6_app.post(
        "/api/v1/talents/jane-doe/brand-deals", json=_make_valid_deal_payload()
    )
    deal_id = created.json()["data"]["brand_deal_id"]

    r = await m6_app.get(f"/api/v1/brand-deals/{deal_id}")
    assert r.status_code == 200
    assert r.json()["data"]["brand_deal_id"] == deal_id


async def test_integration__patch_brand_deal__merges_jsonb(m6_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    await _seed_talent(async_session_factory)
    created = await m6_app.post(
        "/api/v1/talents/jane-doe/brand-deals", json=_make_valid_deal_payload()
    )
    deal_id = created.json()["data"]["brand_deal_id"]

    r = await m6_app.patch(
        f"/api/v1/brand-deals/{deal_id}",
        json={"fee_usd": 7500, "performance_notes": "Big lift on saves."},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["fee_usd"] == 7500
    assert body["data"]["performance_notes"] == "Big lift on saves."
    # Pre-existing fields preserved.
    assert body["data"]["industry_id"] == "activewear"


async def test_integration__set_outcome_endpoint(m6_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    await _seed_talent(async_session_factory)
    created = await m6_app.post(
        "/api/v1/talents/jane-doe/brand-deals",
        json=_make_valid_deal_payload(outcome="pending"),
    )
    deal_id = created.json()["data"]["brand_deal_id"]

    r = await m6_app.post(
        f"/api/v1/brand-deals/{deal_id}/outcome", json={"outcome": "successful_renewed"}
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["outcome"] == "successful_renewed"
    assert body["data"]["outcome"] == "successful_renewed"


async def test_integration__soft_delete_brand_deal(m6_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    await _seed_talent(async_session_factory)
    created = await m6_app.post(
        "/api/v1/talents/jane-doe/brand-deals", json=_make_valid_deal_payload()
    )
    deal_id = created.json()["data"]["brand_deal_id"]

    r = await m6_app.delete(f"/api/v1/brand-deals/{deal_id}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["is_deleted"] is True

    # Soft-deleted rows are excluded from default queries.
    r_after = await m6_app.get("/api/v1/talents/jane-doe/brand-deals")
    assert r_after.status_code == 200
    assert r_after.json()["data"] == []


# ── Honesty floor + auto-link ────────────────────────────────────────


async def test_integration__honesty_floor__missing_as_of_rejected(m6_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    await _seed_talent(async_session_factory)
    bad = _make_valid_deal_payload(
        kpis={"reach": {"value": 100, "source": "platform_verified"}}  # missing as_of
    )
    r = await m6_app.post("/api/v1/talents/jane-doe/brand-deals", json=bad)
    assert r.status_code == 422
    body = r.json()
    assert "errors" in body
    assert any("honesty floor" in e["message"] for e in body["errors"])


async def test_integration__honesty_floor__missing_source_rejected(m6_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    await _seed_talent(async_session_factory)
    bad = _make_valid_deal_payload(
        kpis={"reach": {"value": 100, "as_of": _TODAY}}  # missing source
    )
    r = await m6_app.post("/api/v1/talents/jane-doe/brand-deals", json=bad)
    assert r.status_code == 422
    body = r.json()
    assert "errors" in body


async def test_integration__auto_link_existing_previous_brand(m6_app: AsyncClient) -> None:
    """Light entry on talent.data.previous_brands[] gets the new deal_id FK."""
    from app.db.session import async_session_factory

    await _seed_talent(
        async_session_factory,
        previous_brands=[{"brand": "Gymshark", "industry_id": "activewear"}],
    )
    created = await m6_app.post(
        "/api/v1/talents/jane-doe/brand-deals", json=_make_valid_deal_payload()
    )
    deal_id = created.json()["data"]["brand_deal_id"]

    # Read the talent row directly to confirm the auto-link patch landed.
    async with async_session_factory() as s:
        result = await s.execute(
            text("SELECT data FROM talent WHERE talent_id = :tid"),
            {"tid": "jane-doe"},
        )
        row = result.first()
    assert row is not None
    talent_data = row[0]
    prev = talent_data.get("previous_brands") or []
    assert len(prev) == 1
    assert prev[0]["deal_id"] == deal_id
    assert prev[0]["brand_id"] == "gymshark"


async def test_integration__auto_link_appends_when_no_match(m6_app: AsyncClient) -> None:
    """When the brand isn't already in previous_brands[], the service appends a new entry."""
    from app.db.session import async_session_factory

    await _seed_talent(async_session_factory, previous_brands=[])
    created = await m6_app.post(
        "/api/v1/talents/jane-doe/brand-deals", json=_make_valid_deal_payload()
    )
    deal_id = created.json()["data"]["brand_deal_id"]

    async with async_session_factory() as s:
        result = await s.execute(
            text("SELECT data FROM talent WHERE talent_id = :tid"),
            {"tid": "jane-doe"},
        )
        row = result.first()
    assert row is not None
    talent_data = row[0]
    prev = talent_data.get("previous_brands") or []
    assert len(prev) == 1
    assert prev[0]["brand"] == "Gymshark"
    assert prev[0]["deal_id"] == deal_id


async def test_integration__deal_for_missing_talent_400s(m6_app: AsyncClient) -> None:
    r = await m6_app.post(
        "/api/v1/talents/no-such-talent/brand-deals", json=_make_valid_deal_payload()
    )
    # BusinessRuleError -> 409 per the app's error mapping; check it's a 4xx.
    assert 400 <= r.status_code < 500
