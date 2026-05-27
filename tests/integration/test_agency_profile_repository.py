"""Integration tests for ``AgencyProfileRepository`` against Postgres."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import pytest
from alembic.config import Config

from alembic import command
from app.errors import ConflictError, NotFoundError


@pytest.fixture
def _m4_migrated_db(postgres_container: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # pyright: ignore[reportUnusedFunction]
    """Migrate the testcontainer Postgres to head. Sync — Alembic's env.py
    internally calls ``asyncio.run(...)``, which conflicts with an outer
    running loop (i.e. with async fixtures). Keep migration sync; let the
    session fixture below open the async session separately.
    """
    from pathlib import Path

    url = postgres_container.get_connection_url().replace("+psycopg2", "")
    match = re.match(
        r"postgresql(?:\+\w+)?://(?P<user>[^:]+):(?P<pw>[^@]+)@(?P<host>[^:]+):(?P<port>\d+)/(?P<db>.+)",
        url,
    )
    assert match is not None
    monkeypatch.setenv("POSTGRES_USER", match["user"])
    monkeypatch.setenv("POSTGRES_PASSWORD", match["pw"])
    monkeypatch.setenv("POSTGRES_HOST", match["host"])
    monkeypatch.setenv("POSTGRES_PORT", match["port"])
    monkeypatch.setenv("POSTGRES_DB", match["db"])
    monkeypatch.setenv("DB_MASTER_KEY", "test-master-key-32-bytes-base64==")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-stub")

    from app.config import get_settings

    get_settings.cache_clear()

    repo = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


@pytest.fixture
async def m4_session(_m4_migrated_db: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    """Yield an AsyncSession against the (already-migrated) testcontainer Postgres."""
    # Rebuild the async engine + sessionmaker against the env we just bound.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings

    engine = create_async_engine(live_settings.database_url_async, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def test_integration__get_singleton__empty_returns_none(m4_session: Any) -> None:
    from app.repositories.agency_profile import AgencyProfileRepository

    repo = AgencyProfileRepository(m4_session)
    assert await repo.get_singleton() is None


async def test_integration__create_singleton_then_get(m4_session: Any) -> None:
    from app.repositories.agency_profile import AgencyProfileRepository

    repo = AgencyProfileRepository(m4_session)
    agency_id = uuid4()
    created = await repo.create_singleton(agency_id=agency_id, name="Acme Talent")
    await m4_session.commit()

    fetched = await repo.get_singleton()
    assert fetched is not None
    assert fetched.agency_id == agency_id
    assert fetched.name == "Acme Talent"
    assert fetched.status == "setup_in_progress"
    assert created.agency_id == agency_id


async def test_integration__create_singleton__rejects_duplicate(m4_session: Any) -> None:
    from app.repositories.agency_profile import AgencyProfileRepository

    repo = AgencyProfileRepository(m4_session)
    await repo.create_singleton(agency_id=uuid4(), name="Acme")
    await m4_session.commit()
    with pytest.raises(ConflictError):
        await repo.create_singleton(agency_id=uuid4(), name="Another")


async def test_integration__patch_data__deep_merges(m4_session: Any) -> None:
    from app.repositories.agency_profile import AgencyProfileRepository

    repo = AgencyProfileRepository(m4_session)
    agency_id = uuid4()
    await repo.create_singleton(
        agency_id=agency_id, name="Acme", initial_data={"branding": {"primary_color": "#111111"}}
    )
    await m4_session.commit()

    # First patch: add a sibling field under branding.
    updated = await repo.patch_data(agency_id, {"branding": {"secondary_color": "#222222"}})
    await m4_session.commit()
    assert updated.data["branding"]["primary_color"] == "#111111"
    assert updated.data["branding"]["secondary_color"] == "#222222"

    # Second patch: list replacement (agents) + scalar add.
    updated = await repo.patch_data(
        agency_id,
        {"agents": [{"agent_id": "sarah", "name": "Sarah Chen"}], "domain": "acme.com"},
    )
    await m4_session.commit()
    assert updated.data["agents"] == [{"agent_id": "sarah", "name": "Sarah Chen"}]
    assert updated.data["domain"] == "acme.com"


async def test_integration__patch_data__missing_agency_raises(m4_session: Any) -> None:
    from app.repositories.agency_profile import AgencyProfileRepository

    repo = AgencyProfileRepository(m4_session)
    with pytest.raises(NotFoundError):
        await repo.patch_data(uuid4(), {"any": "value"})


async def test_integration__set_status__updates_row(m4_session: Any) -> None:
    from app.repositories.agency_profile import AgencyProfileRepository

    repo = AgencyProfileRepository(m4_session)
    agency_id = uuid4()
    await repo.create_singleton(agency_id=agency_id, name="Acme")
    await m4_session.commit()

    updated = await repo.set_status(agency_id, "awaiting_dns")
    await m4_session.commit()
    assert updated.status == "awaiting_dns"


async def test_integration__set_status__missing_raises(m4_session: Any) -> None:
    from app.repositories.agency_profile import AgencyProfileRepository

    repo = AgencyProfileRepository(m4_session)
    with pytest.raises(NotFoundError):
        await repo.set_status(uuid4(), "active")
