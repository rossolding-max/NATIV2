"""Integration tests for ``PitchEnrollmentRepository`` against testcontainer Postgres."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from app.repositories.pitch_enrollment import PitchEnrollmentRepository

_TEST_AGENCY_ID = UUID("00000000-0000-0000-0000-0000000000a9")
_TEST_TALENT_ID = "m9-test-talent"
_TEST_BRAND_ID = "m9-test-brand"
_TEST_CONTACT_ID = "bc_m9_test"


@pytest.fixture(scope="module")
def _m9_migrated_db(postgres_container: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


@pytest.fixture
async def session(_m9_migrated_db: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings

    engine = create_async_engine(live_settings.database_url_async, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(
            text("TRUNCATE TABLE pitch_enrollment, brand_contact, talent, brand CASCADE")
        )
        # Seed talent + brand + contact so the FKs are valid.
        await s.execute(
            text(
                "INSERT INTO talent (talent_id, name, status, data, agency_id, "
                "created_at, updated_at, is_deleted) "
                "VALUES (:tid, :name, 'active', :data, :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "tid": _TEST_TALENT_ID,
                "name": "M9 Talent",
                "data": json.dumps({"id": _TEST_TALENT_ID}),
                "agency": str(_TEST_AGENCY_ID),
            },
        )
        await s.execute(
            text(
                "INSERT INTO brand (brand_id, name, industry_id, domain, data, "
                "created_at, updated_at, is_deleted) "
                "VALUES (:bid, :name, :iid, :domain, '{}', "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE) "
                "ON CONFLICT (brand_id) DO NOTHING"
            ),
            {
                "bid": _TEST_BRAND_ID,
                "name": "M9 Brand",
                "iid": "activewear",
                "domain": "m9brand.com",
            },
        )
        await s.execute(
            text(
                "INSERT INTO brand_contact (contact_id, brand_id, name, decision_role, "
                "do_not_contact, data, agency_id, created_at, updated_at, is_deleted) "
                "VALUES (:cid, :bid, :name, 'buyer', FALSE, '{}', :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "cid": _TEST_CONTACT_ID,
                "bid": _TEST_BRAND_ID,
                "name": "Test Contact",
                "agency": str(_TEST_AGENCY_ID),
            },
        )
        await s.commit()
        yield s
    await engine.dispose()


def _draft_payload() -> dict[str, Any]:
    return {
        "steps": [
            {
                "step_number": 1,
                "intent": "first_touch_strongest_angle",
                "subject": "S",
                "body": "B",
                "angles_used": {"primary": "comp_proof"},
                "personalization_fields_used": [],
                "model_used": "claude-haiku-4-5",
                "timing_offset_days": 0,
                "validation_warnings": [],
                "status": "drafted",
            }
        ],
        "engagement_summary": {"sent": 0, "delivered": 0, "opened": 0, "replied": 0},
    }


async def test_integration__insert_draft__creates_awaiting_approval(session: Any) -> None:
    repo = PitchEnrollmentRepository(session, agency_id=_TEST_AGENCY_ID)
    instance = await repo.insert_draft(
        enrollment_id="enr_m9_a",
        talent_id=_TEST_TALENT_ID,
        contact_id=_TEST_CONTACT_ID,
        brand_id=_TEST_BRAND_ID,
        template_id="buyer-direct-pitch",
        agency_id=_TEST_AGENCY_ID,
        data=_draft_payload(),
    )
    await session.commit()
    assert instance.state == "awaiting_approval"
    assert instance.data["steps"][0]["subject"] == "S"


async def test_integration__patch_workflow_state_preserves_other_fields(session: Any) -> None:
    repo = PitchEnrollmentRepository(session, agency_id=_TEST_AGENCY_ID)
    await repo.insert_draft(
        enrollment_id="enr_m9_b",
        talent_id=_TEST_TALENT_ID,
        contact_id=_TEST_CONTACT_ID,
        brand_id=_TEST_BRAND_ID,
        template_id="buyer-direct-pitch",
        agency_id=_TEST_AGENCY_ID,
        data=_draft_payload(),
    )
    await session.commit()
    updated = await repo.patch_workflow_state(
        "enr_m9_b", {"approved_at": "2026-05-28T16:00:00Z", "approved_by": "agent_42"}
    )
    await session.commit()
    assert updated.data["approved_at"] == "2026-05-28T16:00:00Z"
    assert updated.data["approved_by"] == "agent_42"
    # Original steps survive the patch.
    assert updated.data["steps"][0]["subject"] == "S"


async def test_integration__set_killed_stamps_killed_at(session: Any) -> None:
    repo = PitchEnrollmentRepository(session, agency_id=_TEST_AGENCY_ID)
    await repo.insert_draft(
        enrollment_id="enr_m9_c",
        talent_id=_TEST_TALENT_ID,
        contact_id=_TEST_CONTACT_ID,
        brand_id=_TEST_BRAND_ID,
        template_id="buyer-direct-pitch",
        agency_id=_TEST_AGENCY_ID,
        data=_draft_payload(),
    )
    await session.commit()
    when = datetime.now(UTC)
    killed = await repo.set_killed("enr_m9_c", kill_reason="user_killed", killed_at=when)
    await session.commit()
    assert killed.state == "killed"
    assert killed.killed_at is not None
    assert killed.data["kill_reason"] == "user_killed"


async def test_integration__upsert_step_event_appends_and_dedupes(session: Any) -> None:
    repo = PitchEnrollmentRepository(session, agency_id=_TEST_AGENCY_ID)
    await repo.insert_draft(
        enrollment_id="enr_m9_d",
        talent_id=_TEST_TALENT_ID,
        contact_id=_TEST_CONTACT_ID,
        brand_id=_TEST_BRAND_ID,
        template_id="buyer-direct-pitch",
        agency_id=_TEST_AGENCY_ID,
        data=_draft_payload(),
    )
    await session.commit()

    event = {
        "event_type": "email_sent",
        "occurred_at": "2026-05-28T16:00:00Z",
    }
    await repo.upsert_step_event("enr_m9_d", 1, event)
    await repo.upsert_step_event("enr_m9_d", 1, event)  # duplicate; should dedupe
    await session.commit()

    row = await repo.get_by_id("enr_m9_d")
    assert row is not None
    bucket = (row.data or {}).get("events", {}).get("1", [])
    assert len(bucket) == 1  # dedup'd


async def test_integration__find_active_for_contact_excludes_killed(session: Any) -> None:
    repo = PitchEnrollmentRepository(session, agency_id=_TEST_AGENCY_ID)
    await repo.insert_draft(
        enrollment_id="enr_m9_active",
        talent_id=_TEST_TALENT_ID,
        contact_id=_TEST_CONTACT_ID,
        brand_id=_TEST_BRAND_ID,
        template_id="buyer-direct-pitch",
        agency_id=_TEST_AGENCY_ID,
        data=_draft_payload(),
    )
    await repo.insert_draft(
        enrollment_id="enr_m9_killed",
        talent_id=_TEST_TALENT_ID,
        contact_id=_TEST_CONTACT_ID,
        brand_id=_TEST_BRAND_ID,
        template_id="buyer-direct-pitch",
        agency_id=_TEST_AGENCY_ID,
        data=_draft_payload(),
    )
    await repo.set_killed("enr_m9_killed", kill_reason="user_killed")
    await session.commit()
    actives = await repo.find_active_for_contact(_TEST_CONTACT_ID)
    assert {e.enrollment_id for e in actives} == {"enr_m9_active"}
