"""Integration tests for ``BrandCandidateRepository`` against testcontainer Postgres."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from app.repositories.brand_candidate import BrandCandidateRepository

_TEST_AGENCY_ID = UUID("00000000-0000-0000-0000-0000000000a7")


@pytest.fixture(scope="module")
def _m7_migrated_db(postgres_container: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


@pytest.fixture
async def session(_m7_migrated_db: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings

    engine = create_async_engine(live_settings.database_url_async, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(text("TRUNCATE TABLE brand_candidate, talent_vault, talent, brand CASCADE"))
        await s.commit()
        yield s
    await engine.dispose()


async def _seed_talent(s: Any, talent_id: str = "m7-test-talent") -> str:
    await s.execute(
        text(
            "INSERT INTO talent (talent_id, name, status, data, agency_id, "
            "created_at, updated_at, is_deleted) "
            "VALUES (:tid, :name, 'onboarding', :data, :agency, "
            "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
        ),
        {
            "tid": talent_id,
            "name": "M7 Test Talent",
            "data": json.dumps({"id": talent_id}),
            "agency": str(_TEST_AGENCY_ID),
        },
    )
    await s.commit()
    return talent_id


async def _seed_brand(s: Any, brand_id: str = "gymshark", industry_id: str = "activewear") -> str:
    await s.execute(
        text(
            "INSERT INTO brand (brand_id, name, industry_id, data, "
            "created_at, updated_at, is_deleted) "
            "VALUES (:bid, :name, :iid, '{}', "
            "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE) "
            "ON CONFLICT (brand_id) DO NOTHING"
        ),
        {"bid": brand_id, "name": brand_id.capitalize(), "iid": industry_id},
    )
    await s.commit()
    return brand_id


def _payload(brand_id: str, *, score: float = 0.55, tier: str = "primary") -> dict[str, Any]:
    return {
        "brand": brand_id.capitalize(),
        "brand_id": brand_id,
        "industry_id": "activewear",
        "score": score,
        "tier": tier,
        "found_in_searches": 2,
        "sources": [{"search": "primary_industry", "weight": 0.3, "note": ""}],
        "qualification": {"score": 0.6, "tier": "qualified", "signals": []},
    }


async def test_integration__upsert_run_batch__inserts_new_rows(session: Any) -> None:
    await _seed_talent(session)
    await _seed_brand(session)
    repo = BrandCandidateRepository(session, agency_id=_TEST_AGENCY_ID)
    upserted = await repo.upsert_run_batch(
        "m7-test-talent", [_payload("gymshark")], agency_id=_TEST_AGENCY_ID
    )
    await session.commit()
    assert len(upserted) == 1
    assert upserted[0].brand_id == "gymshark"
    assert upserted[0].tier == "primary"


async def test_integration__upsert_run_batch__preserves_workflow_state(session: Any) -> None:
    """A second run keeps user-driven status / notes / pitch_history from the first run."""
    await _seed_talent(session)
    await _seed_brand(session)
    repo = BrandCandidateRepository(session, agency_id=_TEST_AGENCY_ID)

    # First run.
    await repo.upsert_run_batch("m7-test-talent", [_payload("gymshark")], agency_id=_TEST_AGENCY_ID)
    await session.commit()

    # Agent updates the workflow state.
    existing = await repo.get_by_talent_and_brand("m7-test-talent", "gymshark")
    assert existing is not None
    await repo.patch_workflow_state(
        existing.candidate_id,
        {"status": "shortlisted", "user_notes": "interested — checking calendar"},
    )
    await session.commit()

    # Second run with a different score / tier.
    await repo.upsert_run_batch(
        "m7-test-talent",
        [_payload("gymshark", score=0.75, tier="primary")],
        agency_id=_TEST_AGENCY_ID,
    )
    await session.commit()

    refreshed = await repo.get_by_talent_and_brand("m7-test-talent", "gymshark")
    assert refreshed is not None
    assert refreshed.status == "shortlisted"  # workflow-state preserved
    assert refreshed.data["user_notes"].startswith("interested")
    assert refreshed.data["score"] == 0.75  # discovery-output overwritten


async def test_integration__find_by_tier(session: Any) -> None:
    await _seed_talent(session)
    await _seed_brand(session, "gymshark")
    await _seed_brand(session, "nike")
    repo = BrandCandidateRepository(session, agency_id=_TEST_AGENCY_ID)
    await repo.upsert_run_batch(
        "m7-test-talent",
        [
            _payload("gymshark", tier="primary"),
            _payload("nike", tier="secondary"),
        ],
        agency_id=_TEST_AGENCY_ID,
    )
    await session.commit()
    primary = await repo.find_by_tier("m7-test-talent", "primary")
    assert {c.brand_id for c in primary} == {"gymshark"}


async def test_integration__patch_workflow_state_syncs_status_column(session: Any) -> None:
    await _seed_talent(session)
    await _seed_brand(session)
    repo = BrandCandidateRepository(session, agency_id=_TEST_AGENCY_ID)
    upserted = await repo.upsert_run_batch(
        "m7-test-talent", [_payload("gymshark")], agency_id=_TEST_AGENCY_ID
    )
    await session.commit()
    candidate_id = upserted[0].candidate_id

    patched = await repo.patch_workflow_state(candidate_id, {"status": "pitched"})
    await session.commit()
    assert patched.status == "pitched"
    assert patched.data["status"] == "pitched"
