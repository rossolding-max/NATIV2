"""Integration tests for M1's ``0002_initial_schema`` migration.

Skips when Docker is not available (testcontainers can't run). On CI with
Docker, exercises:

1. Upgrade head from baseline → all 16 tables + pgcrypto extension present.
2. Downgrade to 0001 → all 16 tables dropped (pgcrypto stays).
3. Upgrade again → idempotent.
"""

from __future__ import annotations

import os
import re
from typing import Any

import pytest
from alembic.config import Config

from alembic import command

EXPECTED_TABLES = frozenset(
    {
        "agency_profile",
        "brand",
        "brand_candidate",
        "brand_contact",
        "brand_deal",
        "contract_pack",
        "deal",
        "discovery_prep_pack",
        "invoice_pack",
        "memo",
        "performance_report_pack",
        "pitch_angle",
        "pitch_enrollment",
        "pitch_template",
        "proposal_pack",
        "talent",
    }
)


@pytest.fixture
def m1_alembic_cfg(postgres_container: Any, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Alembic config bound to the testcontainers Postgres + the M1 env."""
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
    repo = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    cfg = Config(os.path.join(repo, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(repo, "alembic"))
    return cfg


def _tables_present(postgres_container: Any) -> set[str]:
    """Query Postgres for the set of public-schema tables."""
    import psycopg

    url = postgres_container.get_connection_url().replace("+psycopg2", "")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {row[0] for row in cur.fetchall()}


def _pgcrypto_present(postgres_container: Any) -> bool:
    import psycopg

    url = postgres_container.get_connection_url().replace("+psycopg2", "")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto'")
        return cur.fetchone() is not None


def test_integration__m1_migration_creates_all_16_tables(
    m1_alembic_cfg: Config, postgres_container: Any
) -> None:
    """``alembic upgrade head`` applies 0001 + 0002; 16 tables present + pgcrypto."""
    command.upgrade(m1_alembic_cfg, "head")
    tables = _tables_present(postgres_container)
    assert EXPECTED_TABLES.issubset(tables), (
        f"Missing tables: {EXPECTED_TABLES - tables}\nGot: {sorted(tables)}"
    )
    assert _pgcrypto_present(postgres_container), "pgcrypto extension must be installed"


def test_integration__m1_migration_downgrade_drops_tables(
    m1_alembic_cfg: Config, postgres_container: Any
) -> None:
    """Downgrading past M1 (0001 → drop M1's tables) clears domain tables.

    After M2 added 0003, ``-1`` only rolls back the retrieval_count column.
    To verify M1's table-drop path, downgrade to revision 0001 explicitly
    (one step before M1's 0002).
    """
    command.upgrade(m1_alembic_cfg, "head")
    command.downgrade(m1_alembic_cfg, "0001")
    tables = _tables_present(postgres_container)
    domain_tables_remaining = EXPECTED_TABLES & tables
    assert not domain_tables_remaining, (
        f"After downgrade to 0001, domain tables should be gone but found: "
        f"{sorted(domain_tables_remaining)}"
    )
    # pgcrypto extension is not dropped on downgrade (intentional).
    assert _pgcrypto_present(postgres_container)


def test_integration__m1_migration_round_trip_idempotent(
    m1_alembic_cfg: Config, postgres_container: Any
) -> None:
    """upgrade head → downgrade to 0001 → upgrade head is a no-op cycle."""
    command.upgrade(m1_alembic_cfg, "head")
    command.downgrade(m1_alembic_cfg, "0001")
    command.upgrade(m1_alembic_cfg, "head")
    tables = _tables_present(postgres_container)
    assert EXPECTED_TABLES.issubset(tables)
