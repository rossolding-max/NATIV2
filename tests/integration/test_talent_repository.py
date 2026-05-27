"""Integration tests for ``TalentRepository`` against the testcontainer Postgres."""

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

# Sentinel agency UUID — every talent row carries one (AgencyScopedMixin
# has ``nullable=False``). For integration tests we just need it stable
# across the session so the TalentRepository filter matches.
_TEST_AGENCY_ID = UUID("00000000-0000-0000-0000-0000000000a5")


@pytest.fixture(scope="module")
def _m5_migrated_db(postgres_container: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    """Migrate the testcontainer Postgres to head. Sync (Alembic uses asyncio.run)."""
    repo = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


@pytest.fixture
async def session(_m5_migrated_db: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    """Yield an AsyncSession + truncate talent / talent_vault between tests."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings

    engine = create_async_engine(live_settings.database_url_async, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(text("TRUNCATE TABLE talent_vault, talent CASCADE"))
        await s.commit()
        yield s
    await engine.dispose()


async def _seed_talent(s: Any, talent_id: str, name: str = "Acme Talent") -> None:
    await s.execute(
        text(
            "INSERT INTO talent (talent_id, name, status, data, agency_id, "
            "created_at, updated_at, is_deleted) "
            "VALUES (:tid, :name, 'onboarding', :data, :agency, "
            "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
        ),
        {
            "tid": talent_id,
            "name": name,
            "data": json.dumps({"id": talent_id}),
            "agency": str(_TEST_AGENCY_ID),
        },
    )
    await s.commit()


async def test_integration__get_by_talent_id__returns_row(session: Any) -> None:
    from app.repositories.talent import TalentRepository

    talent_id = f"acme-{uuid4().hex[:8]}"
    await _seed_talent(session, talent_id)

    repo = TalentRepository(session, agency_id=_TEST_AGENCY_ID)
    row = await repo.get_by_talent_id(talent_id)
    assert row is not None
    assert row.talent_id == talent_id


async def test_integration__list_by_status__filters_correctly(session: Any) -> None:
    from app.repositories.talent import TalentRepository

    a = f"a-{uuid4().hex[:8]}"
    b = f"b-{uuid4().hex[:8]}"
    await _seed_talent(session, a, "A")
    await _seed_talent(session, b, "B")

    await session.execute(
        text("UPDATE talent SET status = 'active' WHERE talent_id = :tid"), {"tid": a}
    )
    await session.commit()

    repo = TalentRepository(session, agency_id=_TEST_AGENCY_ID)
    actives = await repo.list_by_status("active")
    onboarding = await repo.list_by_status("onboarding")
    assert {t.talent_id for t in actives} == {a}
    assert {t.talent_id for t in onboarding} == {b}


async def test_integration__patch_data__deep_merges(session: Any) -> None:
    from app.repositories.talent import TalentRepository

    talent_id = f"acme-{uuid4().hex[:8]}"
    await _seed_talent(session, talent_id)

    repo = TalentRepository(session, agency_id=_TEST_AGENCY_ID)
    await repo.patch_data(
        talent_id, {"location": {"country": "US"}, "platforms": [{"platform": "instagram"}]}
    )
    await session.commit()

    row = await repo.get_by_talent_id(talent_id)
    assert row is not None
    assert row.data["location"]["country"] == "US"
    assert row.data["platforms"] == [{"platform": "instagram"}]

    # Second patch — list REPLACES, scalar merges.
    await repo.patch_data(
        talent_id, {"location": {"city": "NYC"}, "platforms": [{"platform": "tiktok"}]}
    )
    await session.commit()

    row = await repo.get_by_talent_id(talent_id)
    assert row is not None
    assert row.data["location"]["country"] == "US"
    assert row.data["location"]["city"] == "NYC"
    assert row.data["platforms"] == [{"platform": "tiktok"}]


async def test_integration__set_status__updates_row(session: Any) -> None:
    from app.repositories.talent import TalentRepository

    talent_id = f"acme-{uuid4().hex[:8]}"
    await _seed_talent(session, talent_id)

    repo = TalentRepository(session, agency_id=_TEST_AGENCY_ID)
    updated = await repo.set_status(talent_id, "active")
    await session.commit()
    assert updated.status == "active"


async def test_integration__missing_talent__raises_not_found(session: Any) -> None:
    from app.repositories.talent import TalentRepository

    repo = TalentRepository(session, agency_id=_TEST_AGENCY_ID)
    with pytest.raises(NotFoundError):
        await repo.patch_data("does-not-exist", {"name": "ghost"})
    with pytest.raises(NotFoundError):
        await repo.set_status("does-not-exist", "active")


async def test_integration__talent_vault__upsert_roundtrip(session: Any) -> None:
    from datetime import UTC, datetime

    from app.repositories.talent_vault import TalentVaultRepository

    talent_id = f"acme-{uuid4().hex[:8]}"
    await _seed_talent(session, talent_id)

    vault = TalentVaultRepository(session)
    await vault.upsert(
        talent_id=talent_id,
        platform="meta",
        access_token="secret-token-meta",
        refresh_token=None,
        expires_at=datetime.now(UTC),
        scopes=["instagram_business_basic"],
    )
    await session.commit()

    fetched = await vault.get(talent_id=talent_id, platform="meta")
    assert fetched is not None
    # EncryptedString decrypts transparently on select.
    assert fetched.access_token == "secret-token-meta"
    assert fetched.scopes == ["instagram_business_basic"]

    # Upsert again with a new token (refresh rotation simulation).
    await vault.upsert(
        talent_id=talent_id,
        platform="meta",
        access_token="rotated-token",
        refresh_token="rotated-refresh",
        expires_at=datetime.now(UTC),
        scopes=["instagram_business_basic", "instagram_business_manage_insights"],
    )
    await session.commit()

    # Open a fresh session for verification: the test session's identity
    # map holds the pre-upsert instance and would return its stale
    # decrypted attribute. Production callers (FastAPI handlers) use a
    # fresh session per request so this only matters in tests.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings
    from app.repositories.talent_vault import TalentVaultRepository

    verify_engine = create_async_engine(live_settings.database_url_async, future=True)
    verify_factory = async_sessionmaker(verify_engine, expire_on_commit=False)
    async with verify_factory() as verify_session:
        fetched = await TalentVaultRepository(verify_session).get(
            talent_id=talent_id, platform="meta"
        )
    await verify_engine.dispose()

    assert fetched is not None
    assert fetched.access_token == "rotated-token"
    assert fetched.refresh_token == "rotated-refresh"
