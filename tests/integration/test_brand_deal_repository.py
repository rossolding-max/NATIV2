"""Integration tests for ``BrandDealRepository`` against testcontainer Postgres."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from app.errors import NotFoundError
from app.models.sqla.brand_deal import BrandDeal
from app.repositories.brand_deal import BrandDealRepository

_TEST_AGENCY_ID = UUID("00000000-0000-0000-0000-0000000000a6")


@pytest.fixture(scope="module")
def _m6_migrated_db(postgres_container: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


@pytest.fixture
async def session(_m6_migrated_db: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings

    engine = create_async_engine(live_settings.database_url_async, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(text("TRUNCATE TABLE brand_deal, talent_vault, talent, brand CASCADE"))
        await s.commit()
        yield s
    await engine.dispose()


async def _seed_talent(s: Any, talent_id: str = "m6-test-talent") -> str:
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
            "data": json.dumps({"id": talent_id, "name": "M6 Test Talent"}),
            "agency": str(_TEST_AGENCY_ID),
        },
    )
    await s.commit()
    return talent_id


async def _seed_brand(s: Any, brand_id: str = "gymshark", industry_id: str = "activewear") -> str:
    """Brand is a global reference table — no ``agency_id`` column."""
    await s.execute(
        text(
            "INSERT INTO brand (brand_id, name, industry_id, data, "
            "created_at, updated_at, is_deleted) "
            "VALUES (:bid, :name, :iid, '{}', "
            "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE) "
            "ON CONFLICT (brand_id) DO NOTHING"
        ),
        {
            "bid": brand_id,
            "name": brand_id.capitalize(),
            "iid": industry_id,
        },
    )
    await s.commit()
    return brand_id


async def _make_deal(
    s: Any, *, deal_id: str, talent_id: str, brand_id: str, outcome: str = "pending"
) -> BrandDeal:
    repo = BrandDealRepository(s, agency_id=_TEST_AGENCY_ID)
    deal = BrandDeal(
        brand_deal_id=deal_id,
        talent_id=talent_id,
        brand_id=brand_id,
        outcome=outcome,
        data={
            "deal_id": deal_id,
            "brand_id": brand_id,
            "industry_id": "activewear",
            "outcome": outcome,
        },
    )
    created = await repo.create(deal)
    await s.commit()
    return created


async def test_integration__find_by_talent__returns_all_deals(session: Any) -> None:
    await _seed_talent(session)
    await _seed_brand(session)
    await _make_deal(
        session,
        deal_id=f"deal_2025_a_{uuid4().hex[:6]}",
        talent_id="m6-test-talent",
        brand_id="gymshark",
    )
    await _make_deal(
        session,
        deal_id=f"deal_2024_a_{uuid4().hex[:6]}",
        talent_id="m6-test-talent",
        brand_id="gymshark",
    )

    repo = BrandDealRepository(session, agency_id=_TEST_AGENCY_ID)
    deals = await repo.find_by_talent("m6-test-talent")
    assert len(deals) == 2


async def test_integration__find_by_outcome__filters_correctly(session: Any) -> None:
    await _seed_talent(session)
    await _seed_brand(session)
    await _make_deal(
        session,
        deal_id=f"deal_a_{uuid4().hex[:6]}",
        talent_id="m6-test-talent",
        brand_id="gymshark",
        outcome="successful",
    )
    await _make_deal(
        session,
        deal_id=f"deal_b_{uuid4().hex[:6]}",
        talent_id="m6-test-talent",
        brand_id="gymshark",
        outcome="underperformed",
    )

    repo = BrandDealRepository(session, agency_id=_TEST_AGENCY_ID)
    successful = await repo.find_by_outcome("m6-test-talent", "successful")
    assert len(successful) == 1
    assert successful[0].outcome == "successful"


async def test_integration__patch_deal_data__deep_merges_jsonb(session: Any) -> None:
    await _seed_talent(session)
    await _seed_brand(session)
    deal_id = f"deal_2025_acme_{uuid4().hex[:6]}"
    await _make_deal(session, deal_id=deal_id, talent_id="m6-test-talent", brand_id="gymshark")
    repo = BrandDealRepository(session, agency_id=_TEST_AGENCY_ID)
    updated = await repo.patch_deal_data(
        deal_id, {"fee_usd": 5000, "kpis": {"reach": {"value": 1_000_000}}}
    )
    await session.commit()
    assert updated.data["fee_usd"] == 5000
    assert updated.data["kpis"]["reach"]["value"] == 1_000_000
    # Pre-existing keys preserved.
    assert updated.data["industry_id"] == "activewear"
    # last_updated_at gets bumped.
    assert updated.last_updated_at is not None


async def test_integration__set_outcome_column__updates_indexed_column(session: Any) -> None:
    await _seed_talent(session)
    await _seed_brand(session)
    deal_id = f"deal_2025_acme_{uuid4().hex[:6]}"
    await _make_deal(
        session, deal_id=deal_id, talent_id="m6-test-talent", brand_id="gymshark", outcome="pending"
    )
    repo = BrandDealRepository(session, agency_id=_TEST_AGENCY_ID)
    updated = await repo.set_outcome_column(deal_id, "successful")
    await session.commit()
    assert updated.outcome == "successful"


async def test_integration__patch_deal_data__raises_on_missing_deal(session: Any) -> None:
    repo = BrandDealRepository(session, agency_id=_TEST_AGENCY_ID)
    with pytest.raises(NotFoundError):
        await repo.patch_deal_data("deal_2025_nope_abcdef", {"fee_usd": 100})
