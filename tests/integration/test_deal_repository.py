"""DealRepository — finders + patch_workflow_state + insert_manual_deal."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.errors import BusinessRuleError
from app.repositories.deal import DealRepository

_SENTINEL_AGENCY_ID = UUID(int=0)
_TALENT_ID = "m10-repo-talent"
_BRAND_ID = "m10-repo-brand"
_CONTACT_ID = "bc_m10_repo"


@pytest.fixture
def _m10_repo_setup(  # pyright: ignore[reportUnusedFunction]
    postgres_container: Any,
    minio_container: Any,
    redis_container: Any,
) -> Any:
    _ = redis_container
    _ = minio_container
    repo_dir = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo_dir / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


@pytest.fixture
async def m10_repo_db(_m10_repo_setup: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    from app.config import settings as live_settings

    engine = create_async_engine(live_settings.database_url_async, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as s:
        await s.execute(
            text(
                "TRUNCATE TABLE pitch_enrollment, brand_contact, brand_candidate, "
                "brand_deal, talent_vault, talent, brand, agency_profile, "
                "memo, deal CASCADE"
            )
        )
        await s.execute(
            text(
                "INSERT INTO talent (talent_id, name, status, data, agency_id, "
                "created_at, updated_at, is_deleted) "
                "VALUES (:tid, :name, 'active', :data, :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "tid": _TALENT_ID,
                "name": "Repo Talent",
                "data": json.dumps({"id": _TALENT_ID}),
                "agency": str(_SENTINEL_AGENCY_ID),
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
                "bid": _BRAND_ID,
                "name": "Repo Brand",
                "iid": "activewear",
                "domain": "m10repo.com",
            },
        )
        await s.execute(
            text(
                "INSERT INTO brand_contact (contact_id, brand_id, name, decision_role, "
                "email, do_not_contact, data, agency_id, created_at, updated_at, is_deleted) "
                "VALUES (:cid, :bid, :name, 'buyer', "
                "pgp_sym_encrypt(:email, current_setting('app.master_key', true)), "
                "FALSE, '{}', :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "cid": _CONTACT_ID,
                "bid": _BRAND_ID,
                "name": "Repo Contact",
                "email": "repo-contact@m10repo.com",
                "agency": str(_SENTINEL_AGENCY_ID),
            },
        )
        await s.commit()

    try:
        yield factory
    finally:
        await engine.dispose()


async def _make_deal(
    factory: async_sessionmaker[AsyncSession],
    *,
    by_agent_id: str = "agent_alice",
) -> str:
    async with factory() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        deal = await repo.insert_manual_deal(
            talent_id=_TALENT_ID,
            brand_id=_BRAND_ID,
            primary_contact_id=_CONTACT_ID,
            by_agent_id=by_agent_id,
        )
        await s.commit()
        return deal.deal_id


# ── finders ────────────────────────────────────────────────────────


async def test_integration__find_by_talent_returns_only_non_terminal_by_default(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    deal_a = await _make_deal(m10_repo_db)
    deal_b = await _make_deal(m10_repo_db)
    # Mark deal_a terminal via direct SQL (skipping the orchestrator).
    async with m10_repo_db() as s:
        await s.execute(
            text(
                "UPDATE deal SET is_terminal = TRUE, substage = 'disqualified' WHERE deal_id = :did"
            ),
            {"did": deal_a},
        )
        await s.commit()

    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        rows = await repo.find_by_talent(_TALENT_ID)
        ids = {r.deal_id for r in rows}
        assert deal_b in ids
        assert deal_a not in ids

        rows_all = await repo.find_by_talent(_TALENT_ID, include_terminal=True)
        ids_all = {r.deal_id for r in rows_all}
        assert {deal_a, deal_b} <= ids_all


async def test_integration__find_by_brand_basic(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    await _make_deal(m10_repo_db)
    await _make_deal(m10_repo_db)
    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        rows = await repo.find_by_brand(_BRAND_ID)
        assert len(rows) == 2


async def test_integration__find_by_stage_lead(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    await _make_deal(m10_repo_db)
    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        rows = await repo.find_by_stage("lead")
        assert len(rows) == 1


async def test_integration__find_due_for_action(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    deal_id = await _make_deal(m10_repo_db)
    past = datetime(2020, 1, 1, tzinfo=UTC)
    future = datetime(2099, 1, 1, tzinfo=UTC)
    async with m10_repo_db() as s:
        await s.execute(
            text("UPDATE deal SET next_action_due_at = :ts WHERE deal_id = :did"),
            {"ts": past, "did": deal_id},
        )
        await s.commit()

    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        rows = await repo.find_due_for_action(datetime.now(UTC))
        assert any(r.deal_id == deal_id for r in rows)

        # Future-dated work isn't returned.
        rows_empty = await repo.find_due_for_action(past - timedelta(days=1))
        assert all(r.deal_id != deal_id for r in rows_empty)
        _ = future


# ── find_ready_for_prep_pack ───────────────────────────────────────


async def test_integration__find_ready_for_prep_pack_filters_substage_and_pack_id(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    deal_id = await _make_deal(m10_repo_db)
    # Not yet at initial_call_scheduled — should not be returned.
    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        assert await repo.find_ready_for_prep_pack() == []

    # Move to initial_call_scheduled.
    async with m10_repo_db() as s:
        await s.execute(
            text("UPDATE deal SET substage = 'initial_call_scheduled' WHERE deal_id = :did"),
            {"did": deal_id},
        )
        await s.commit()

    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        rows = await repo.find_ready_for_prep_pack()
        assert any(r.deal_id == deal_id for r in rows)


async def test_integration__find_ready_for_prep_pack_respects_debounce_stamp(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    """A deal stamped <1 hour ago is skipped; >1 hour is retried."""
    deal_id = await _make_deal(m10_repo_db)
    async with m10_repo_db() as s:
        await s.execute(
            text(
                "UPDATE deal SET substage = 'initial_call_scheduled', "
                "data = jsonb_set(data, '{prep_pack_enqueued_at}', "
                "to_jsonb(CAST(:stamp AS text))) WHERE deal_id = :did"
            ),
            {"stamp": datetime.now(UTC).isoformat(), "did": deal_id},
        )
        await s.commit()

    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        rows = await repo.find_ready_for_prep_pack()
        assert all(r.deal_id != deal_id for r in rows)

    # Now backdate the stamp >1 hour — should resurface.
    async with m10_repo_db() as s:
        old_stamp = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        await s.execute(
            text(
                "UPDATE deal SET data = jsonb_set(data, '{prep_pack_enqueued_at}', "
                "to_jsonb(CAST(:stamp AS text))) WHERE deal_id = :did"
            ),
            {"stamp": old_stamp, "did": deal_id},
        )
        await s.commit()

    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        rows = await repo.find_ready_for_prep_pack()
        assert any(r.deal_id == deal_id for r in rows)


async def test_integration__find_ready_for_prep_pack_skips_when_pack_id_already_set(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    deal_id = await _make_deal(m10_repo_db)
    async with m10_repo_db() as s:
        await s.execute(
            text(
                "UPDATE deal SET substage = 'initial_call_scheduled', "
                "latest_prep_pack_id = 'pack_done' WHERE deal_id = :did"
            ),
            {"did": deal_id},
        )
        await s.commit()

    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        rows = await repo.find_ready_for_prep_pack()
        assert all(r.deal_id != deal_id for r in rows)


# ── find_ready_for_archive — 3 gate check ─────────────────────────


async def test_integration__find_ready_for_archive_requires_all_three_gates(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    deal_id = await _make_deal(m10_repo_db)
    # Move to post_campaign_reporting; gates start empty.
    async with m10_repo_db() as s:
        await s.execute(
            text(
                "UPDATE deal SET substage = 'post_campaign_reporting', "
                "stage = 'close' WHERE deal_id = :did"
            ),
            {"did": deal_id},
        )
        await s.commit()

    # No gates set -> not ready.
    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        rows = await repo.find_ready_for_archive()
        assert all(r.deal_id != deal_id for r in rows)

    # Set 2 of 3 gates -> still not ready.
    async with m10_repo_db() as s:
        await s.execute(
            text(
                "UPDATE deal SET data = jsonb_set(data, '{close}', CAST(:close AS jsonb)) "
                "WHERE deal_id = :did"
            ),
            {
                "close": json.dumps(
                    {
                        "all_invoices_paid_at": "2026-05-01T00:00:00+00:00",
                        "final_kpis": {"reach": 1000},
                    }
                ),
                "did": deal_id,
            },
        )
        await s.commit()

    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        rows = await repo.find_ready_for_archive()
        assert all(r.deal_id != deal_id for r in rows)

    # Set the 3rd gate -> ready.
    async with m10_repo_db() as s:
        await s.execute(
            text(
                "UPDATE deal SET data = jsonb_set(data, '{close}', CAST(:close AS jsonb)) "
                "WHERE deal_id = :did"
            ),
            {
                "close": json.dumps(
                    {
                        "all_invoices_paid_at": "2026-05-01T00:00:00+00:00",
                        "final_kpis": {"reach": 1000},
                        "final_performance_report_attachment_id": "att_xyz",
                    }
                ),
                "did": deal_id,
            },
        )
        await s.commit()

    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        rows = await repo.find_ready_for_archive()
        assert any(r.deal_id == deal_id for r in rows)


# ── patch_workflow_state — guard rails ────────────────────────────


async def test_integration__patch_refuses_direct_stage_write(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    deal_id = await _make_deal(m10_repo_db)
    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        with pytest.raises(BusinessRuleError, match="stage"):
            await repo.patch_workflow_state(deal_id, {"stage": "proposal"})


async def test_integration__patch_refuses_direct_substage_write(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    deal_id = await _make_deal(m10_repo_db)
    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        with pytest.raises(BusinessRuleError, match="substage"):
            await repo.patch_workflow_state(deal_id, {"substage": "qualified"})


async def test_integration__patch_refuses_loss_block_in_data_diff(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    deal_id = await _make_deal(m10_repo_db)
    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        with pytest.raises(BusinessRuleError, match="/loss"):
            await repo.patch_workflow_state(deal_id, {"data": {"loss": {"reason": "budget"}}})


async def test_integration__patch_preserves_stage_history(
    m10_repo_db: async_sessionmaker[AsyncSession],
) -> None:
    """A workflow patch must NOT clobber the opening stage_history entry."""
    deal_id = await _make_deal(m10_repo_db)
    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        await repo.patch_workflow_state(deal_id, {"data": {"user_notes": "hi"}})
        await s.commit()

    async with m10_repo_db() as s:
        repo = DealRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        deal = await repo.get_by_id(deal_id)
        assert deal is not None
        history = (deal.data or {}).get("stage_history") or []
        assert len(history) == 1
        assert history[0]["substage"] == "new_lead"
        assert deal.data["user_notes"] == "hi"
