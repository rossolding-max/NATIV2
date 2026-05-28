"""M6 — end-to-end happy path against testcontainer Postgres.

Boots the lifespan, seeds a talent, creates three brand_deals across
three outcomes (successful_renewed / successful / underperformed),
patches one of them, sets outcome on another, soft-deletes a third,
and confirms each step landed correctly via list filters + GET.
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
def _m6_e2e_setup(  # pyright: ignore[reportUnusedFunction]
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
async def m6_app(_m6_e2e_setup: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
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


async def _seed_talent(db_session_factory: Any, *, talent_id: str = "m6-test-talent") -> str:
    """Insert a minimal talent row with a single existing light brand entry."""
    import json as _json
    from uuid import UUID

    async with db_session_factory() as s:
        await s.execute(
            text(
                "INSERT INTO talent (talent_id, name, status, data, agency_id, "
                "created_at, updated_at, is_deleted) "
                "VALUES (:tid, :name, 'onboarding', :data, :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "tid": talent_id,
                "name": "M6 Test Talent",
                "data": _json.dumps(
                    {
                        "id": talent_id,
                        "name": "M6 Test Talent",
                        "previous_brands": [{"brand": "Gymshark", "industry_id": "activewear"}],
                    }
                ),
                "agency": str(UUID(int=0)),
            },
        )
        await s.commit()
    return talent_id


def _deal(brand_name: str, outcome: str, fee: int = 5000) -> dict[str, Any]:
    return {
        "brand_name": brand_name,
        "industry_id": "activewear",
        "campaign_type": "sponsored_post",
        "outcome": outcome,
        "started_at": "2025-06-01",
        "ended_at": "2025-06-30",
        "fee_usd": fee,
        "kpis": {
            "reach": {
                "value": 1_000_000,
                "source": "platform_verified",
                "as_of": _TODAY,
            }
        },
    }


async def test_e2e__three_deals_across_outcomes(m6_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    await _seed_talent(async_session_factory)

    # Create three deals across three outcomes.
    deal_a = (
        await m6_app.post(
            "/api/v1/talents/m6-test-talent/brand-deals",
            json=_deal("Gymshark", "successful_renewed", fee=8000),
        )
    ).json()["data"]
    deal_b = (
        await m6_app.post(
            "/api/v1/talents/m6-test-talent/brand-deals",
            json=_deal("Nike", "successful", fee=12000),
        )
    ).json()["data"]
    deal_c = (
        await m6_app.post(
            "/api/v1/talents/m6-test-talent/brand-deals",
            json=_deal("Adidas", "underperformed", fee=4000),
        )
    ).json()["data"]

    # All three landed.
    all_deals = (await m6_app.get("/api/v1/talents/m6-test-talent/brand-deals")).json()["data"]
    assert len(all_deals) == 3
    assert {d["brand_id"] for d in all_deals} == {"gymshark", "nike", "adidas"}

    # Filter by outcome.
    successful = (
        await m6_app.get("/api/v1/talents/m6-test-talent/brand-deals?outcome=successful")
    ).json()["data"]
    assert {d["brand_id"] for d in successful} == {"nike"}

    # Patch deal_a — bump fee + add a performance note.
    r_patch = await m6_app.patch(
        f"/api/v1/brand-deals/{deal_a['brand_deal_id']}",
        json={"fee_usd": 9500, "performance_notes": "Renewed for Q1 — strong saves lift."},
    )
    assert r_patch.status_code == 200, r_patch.text
    patched = r_patch.json()["data"]
    assert patched["fee_usd"] == 9500
    assert patched["data"]["performance_notes"].startswith("Renewed")

    # Flip deal_c's outcome via the dedicated endpoint.
    r_outcome = await m6_app.post(
        f"/api/v1/brand-deals/{deal_c['brand_deal_id']}/outcome",
        json={"outcome": "mixed"},
    )
    assert r_outcome.status_code == 200, r_outcome.text
    assert r_outcome.json()["data"]["outcome"] == "mixed"

    # Soft-delete deal_b.
    r_delete = await m6_app.delete(f"/api/v1/brand-deals/{deal_b['brand_deal_id']}")
    assert r_delete.status_code == 200, r_delete.text

    # After soft-delete, list shows only the surviving two.
    surviving = (await m6_app.get("/api/v1/talents/m6-test-talent/brand-deals")).json()["data"]
    assert len(surviving) == 2
    assert deal_b["brand_deal_id"] not in {d["brand_deal_id"] for d in surviving}

    # Auto-link to talent.data.previous_brands[] kept the index in sync.
    async with async_session_factory() as s:
        result = await s.execute(
            text("SELECT data FROM talent WHERE talent_id = 'm6-test-talent'"),
        )
        row = result.first()
    assert row is not None
    prev = row[0]["previous_brands"]
    # Gymshark already had a light entry; the auto-link patched its deal_id back.
    gymshark_entry = next((e for e in prev if e["brand_id"] == "gymshark"), None)
    assert gymshark_entry is not None
    assert gymshark_entry["deal_id"] == deal_a["brand_deal_id"]
    # Nike + Adidas got appended as new light entries with their deal_ids.
    assert {e["brand_id"] for e in prev} == {"gymshark", "nike", "adidas"}
