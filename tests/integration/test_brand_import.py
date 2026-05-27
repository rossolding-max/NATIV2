"""M1 ACCEPTANCE TEST: brand_industry_map round-trip.

Per ``docs/project_plan.md`` § M1 acceptance: load 290 records from
``data/brand_industry_map.json`` into Postgres; re-export semantically
identical to the source file.

"Semantically identical after canonicalisation" per the M1 plan's
stress-test gap fix — byte-identical is unachievable because Pydantic
canonicalises JSON keys (sort order) and Python's Decimal/datetime
serialisation differs from the JSON source's bare numbers/strings.
We canonicalise both sides via ``json.dumps(..., sort_keys=True)``
before comparing.

Skipped without Docker.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config

from alembic import command

REPO = Path(__file__).resolve().parents[2]
SOURCE_FILE = REPO / "data" / "brand_industry_map.json"


@pytest.fixture
def m1_seeded_db(postgres_container: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Migrate the testcontainer Postgres to M1 head + return it."""
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
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


def _reconstruct_record_from_row(row: tuple[Any, ...], columns: list[str]) -> dict[str, Any]:
    """Reverse the import: merge top-level columns back into the data payload.

    Yields a record matching the original JSON shape.
    """
    record: dict[str, Any] = {}
    for col, val in zip(columns, row, strict=True):
        if col == "data":
            # data is a dict already (JSONB → psycopg returns dict).
            for k, v in val.items():
                record[k] = v
        elif col == "brand_id":
            continue  # derived from name; not in the source JSON
        else:
            if val is not None:
                record[col] = val
    return record


def test_acceptance__brand_industry_map_imports_290_records(m1_seeded_db: Any) -> None:
    """Run the import script + verify 290 rows present."""
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "import_brand_industry_map.py")],
        cwd=REPO,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        result.returncode == 0
    ), f"Import script failed.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "Imported 290 new brand" in result.stdout

    # Verify directly via psycopg.
    import psycopg

    url = m1_seeded_db.get_connection_url().replace("+psycopg2", "")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM brand")
        count = cur.fetchone()
        assert count is not None
        assert count[0] == 290, f"Expected 290 rows, got {count[0]}"


def test_acceptance__brand_industry_map_idempotent_reimport(m1_seeded_db: Any) -> None:
    """Re-running the import skips all existing rows (no duplicates).

    Per the M1 plan locked decision: insert-only + skip-existing on re-run.
    """
    # First import.
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "import_brand_industry_map.py")],
        cwd=REPO,
        env={**os.environ},
        capture_output=True,
        text=True,
        check=True,
    )
    # Second import — should skip all 290.
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "import_brand_industry_map.py")],
        cwd=REPO,
        env={**os.environ},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Imported 0 new brand" in result.stdout
    assert "skipped 290 existing" in result.stdout


def test_acceptance__brand_industry_map_round_trip_canonicalised(m1_seeded_db: Any) -> None:
    """Import 290 records → re-export → compare canonicalised JSON.

    "Semantically identical after canonicalisation" — both sides pass
    through ``json.dumps(..., sort_keys=True)`` then compare. This handles
    Pydantic's alphabetised field output, Decimal-to-string conversions,
    and similar canonicalisation differences.
    """
    # Import.
    subprocess.run(
        [sys.executable, str(REPO / "scripts" / "import_brand_industry_map.py")],
        cwd=REPO,
        env={**os.environ},
        capture_output=True,
        text=True,
        check=True,
    )

    # Re-export by querying the brand table.
    import psycopg

    url = m1_seeded_db.get_connection_url().replace("+psycopg2", "")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT brand_id, name, industry_id, domain, hq_country,
                   company_stage, typical_campaign_tier, data
            FROM brand
            ORDER BY name
            """
        )
        columns = [
            "brand_id",
            "name",
            "industry_id",
            "domain",
            "hq_country",
            "company_stage",
            "typical_campaign_tier",
            "data",
        ]
        rows = cur.fetchall()
    assert len(rows) == 290

    exported_records = [_reconstruct_record_from_row(r, columns) for r in rows]

    # Compare canonicalised JSON: each record from source vs each from DB.
    source_doc = json.loads(SOURCE_FILE.read_text())
    source_records = sorted(source_doc["brands"], key=lambda r: r["name"])
    exported_sorted = sorted(exported_records, key=lambda r: r["name"])

    for i, (src, exp) in enumerate(zip(source_records, exported_sorted, strict=True)):
        src_canonical = json.dumps(src, sort_keys=True, default=str)
        exp_canonical = json.dumps(exp, sort_keys=True, default=str)
        assert src_canonical == exp_canonical, (
            f"Record {i} ({src.get('name')!r}) differs after canonicalisation.\n"
            f"src:  {src_canonical[:300]}\n"
            f"exp:  {exp_canonical[:300]}"
        )
