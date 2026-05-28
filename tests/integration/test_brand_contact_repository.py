"""Integration tests for ``BrandContactRepository`` against testcontainer Postgres."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from app.repositories.brand_contact import BrandContactRepository

_TEST_AGENCY_ID = UUID("00000000-0000-0000-0000-0000000000a8")
_TEST_BRAND_ID = "m8-test-brand"


@pytest.fixture(scope="module")
def _m8_migrated_db(postgres_container: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


@pytest.fixture
async def session(_m8_migrated_db: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings

    engine = create_async_engine(live_settings.database_url_async, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(text("TRUNCATE TABLE brand_contact, brand CASCADE"))
        await s.commit()
        yield s
    await engine.dispose()


async def _seed_brand(s: Any, brand_id: str = _TEST_BRAND_ID) -> str:
    await s.execute(
        text(
            "INSERT INTO brand (brand_id, name, industry_id, data, "
            "created_at, updated_at, is_deleted) "
            "VALUES (:bid, :name, :iid, '{}', "
            "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE) "
            "ON CONFLICT (brand_id) DO NOTHING"
        ),
        {"bid": brand_id, "name": brand_id.replace("-", " ").title(), "iid": "activewear"},
    )
    await s.commit()
    return brand_id


def _payload(
    contact_id: str,
    *,
    name: str = "Alice Smith",
    decision_role: str = "buyer",
    email: dict[str, Any] | None = None,
    do_not_contact: bool = False,
) -> dict[str, Any]:
    return {
        "contact_id": contact_id,
        "name": name,
        "decision_role": decision_role,
        "title": "VP Marketing",
        "seniority": "vp",
        "email": email or {"address": "alice@brand.com", "verification_status": "verified"},
        "do_not_contact": do_not_contact,
        "qualification": {"score": 0.7, "tier": "qualified", "signals": []},
    }


async def test_integration__upsert_run_batch__inserts_new_rows(session: Any) -> None:
    await _seed_brand(session)
    repo = BrandContactRepository(session, agency_id=_TEST_AGENCY_ID)
    upserted = await repo.upsert_run_batch(
        _TEST_BRAND_ID, [_payload("bc_m8_alice")], agency_id=_TEST_AGENCY_ID
    )
    await session.commit()
    assert len(upserted) == 1
    row = upserted[0]
    assert row.contact_id == "bc_m8_alice"
    assert row.brand_id == _TEST_BRAND_ID
    assert row.decision_role == "buyer"
    assert row.email == "alice@brand.com"
    assert row.do_not_contact is False


async def test_integration__upsert_run_batch__preserves_workflow_state(session: Any) -> None:
    """An agent-set ``do_not_contact`` survives a fresh enrichment that doesn't carry it."""
    await _seed_brand(session)
    repo = BrandContactRepository(session, agency_id=_TEST_AGENCY_ID)

    # First run — establish the row.
    await repo.upsert_run_batch(_TEST_BRAND_ID, [_payload("bc_m8_dnc")], agency_id=_TEST_AGENCY_ID)
    await session.commit()

    # Agent flips do_not_contact via patch_workflow_state.
    await repo.patch_workflow_state(
        "bc_m8_dnc",
        {"do_not_contact": True, "do_not_contact_reason": "opted out via reply"},
    )
    await session.commit()

    # Second enrichment run — payload doesn't include do_not_contact.
    upserted = await repo.upsert_run_batch(
        _TEST_BRAND_ID,
        [_payload("bc_m8_dnc", decision_role="influencer")],
        agency_id=_TEST_AGENCY_ID,
    )
    await session.commit()
    row = upserted[0]
    # Discovery overwrote decision_role.
    assert row.decision_role == "influencer"
    # Workflow state preserved.
    assert row.do_not_contact is True
    assert row.data.get("do_not_contact_reason") == "opted out via reply"


async def test_integration__find_by_brand(session: Any) -> None:
    await _seed_brand(session)
    repo = BrandContactRepository(session, agency_id=_TEST_AGENCY_ID)
    await repo.upsert_run_batch(
        _TEST_BRAND_ID,
        [_payload("bc_m8_a", name="Alice"), _payload("bc_m8_b", name="Bob")],
        agency_id=_TEST_AGENCY_ID,
    )
    await session.commit()
    rows = await repo.find_by_brand(_TEST_BRAND_ID)
    assert {r.contact_id for r in rows} == {"bc_m8_a", "bc_m8_b"}


async def test_integration__find_pitchable_excludes_dnc(session: Any) -> None:
    """``find_pitchable_for_talent`` skips ``do_not_contact=True`` rows."""
    await _seed_brand(session)
    repo = BrandContactRepository(session, agency_id=_TEST_AGENCY_ID)
    await repo.upsert_run_batch(
        _TEST_BRAND_ID,
        [
            _payload("bc_m8_clean", name="Clean"),
            _payload("bc_m8_dnc", name="DNC", do_not_contact=True),
        ],
        agency_id=_TEST_AGENCY_ID,
    )
    await session.commit()
    rows = await repo.find_pitchable_for_talent("talent-1", _TEST_BRAND_ID)
    assert {r.contact_id for r in rows} == {"bc_m8_clean"}


async def test_integration__patch_workflow_state_syncs_email_column(session: Any) -> None:
    """Patching ``email`` in JSONB syncs the scalar mirror column."""
    await _seed_brand(session)
    repo = BrandContactRepository(session, agency_id=_TEST_AGENCY_ID)
    await repo.upsert_run_batch(_TEST_BRAND_ID, [_payload("bc_m8_e")], agency_id=_TEST_AGENCY_ID)
    await session.commit()
    updated = await repo.patch_workflow_state(
        "bc_m8_e",
        {"email": {"address": "alice.new@brand.com", "verification_status": "verified"}},
    )
    await session.commit()
    assert updated.email == "alice.new@brand.com"
