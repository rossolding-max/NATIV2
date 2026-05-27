"""Alembic upgrade / downgrade round-trip on a testcontainers Postgres.

Proves the empty baseline migration applies + reverts cleanly. M1's first
real migration extends this fixture pattern (and adds compare-type checks).
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from alembic import command
from alembic.config import Config


@pytest.fixture
def alembic_cfg(postgres_container: Any, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Alembic config bound to the testcontainers Postgres.

    We monkeypatch POSTGRES_* env vars so ``app.config.settings`` resolves to
    the container's DSN when ``alembic/env.py`` imports it.
    """
    url = postgres_container.get_connection_url().replace("+psycopg2", "")
    # Strip "postgresql+psycopg://" prefix to get user:pw@host:port/db.
    import re

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
    # Required-at-boot vars
    monkeypatch.setenv("DB_MASTER_KEY", "test-master-key-32-bytes-base64==")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-stub")

    # Force `app.config.get_settings` to re-load with the patched env.
    from app.config import get_settings

    get_settings.cache_clear()

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    cfg = Config(os.path.join(repo_root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(repo_root, "alembic"))
    return cfg


def test_integration__alembic_upgrade_head_applies_baseline(alembic_cfg: Config) -> None:
    """``alembic upgrade head`` applies all migrations + creates the version table.

    After M1 PR 2, head is `0002_initial_schema` (M1). Before M1 it was
    `0001_empty_baseline`. This test asserts only that the version table
    is populated with a non-empty revision id — it doesn't pin the exact
    head value, so it survives future migrations.
    """
    command.upgrade(alembic_cfg, "head")

    # Verify alembic_version table populated.
    import asyncio

    from sqlalchemy import text

    from app.db.session import async_session_factory

    async def _verify() -> None:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT version_num FROM alembic_version"))
            rows = result.fetchall()
            assert len(rows) == 1
            assert rows[0][0], "alembic_version should hold the head revision id"

    asyncio.run(_verify())


def test_integration__alembic_downgrade_then_upgrade_idempotent(alembic_cfg: Config) -> None:
    """``upgrade head`` then ``downgrade base`` then ``upgrade head`` is a no-op cycle.

    Establishes the migration is reversible — M1's first real migration must
    also pass this discipline before it lands.
    """
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    # If we got here without exceptions, the cycle is clean.
