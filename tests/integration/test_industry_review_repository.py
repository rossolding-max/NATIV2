"""M7.7 — IndustryReviewRepository unit tests (in-memory mocked session)."""

from __future__ import annotations

# These tests live in tests/integration for the real DB path. The unit
# tier validates the patch_items / mark_approved invariants against the
# repository's pure-Python branches via testcontainer Postgres so the
# JSONB roundtrip is real.
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic.config import Config
from sqlalchemy import text

from alembic import command
from app.errors import BusinessRuleError, NotFoundError
from app.repositories.industry_review import IndustryReviewRepository

_SENTINEL_AGENCY_ID = UUID(int=0)
_TEST_TALENT_ID = "ir-test-talent"


@pytest.fixture
def _ir_setup_env(  # pyright: ignore[reportUnusedFunction]
    postgres_container: Any,
    minio_container: Any,
    redis_container: Any,
) -> Any:
    _ = redis_container
    _ = minio_container
    repo = Path(__file__).resolve().parents[3]
    cfg = Config(str(repo / "alembic.ini"))
    cfg.set_main_option("script_location", str(repo / "alembic"))
    command.upgrade(cfg, "head")
    return postgres_container


@pytest.fixture
async def ir_session(_ir_setup_env: Any):  # pyright: ignore[reportUnusedFunction]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings

    engine = create_async_engine(live_settings.database_url_async, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        await s.execute(
            text(
                "TRUNCATE TABLE industry_review, brand_candidate, brand_deal, "
                "talent_vault, talent CASCADE"
            )
        )
        await s.execute(
            text(
                "INSERT INTO talent (talent_id, name, status, data, agency_id, "
                "created_at, updated_at, is_deleted) "
                "VALUES (:tid, 'IR Talent', 'onboarding', '{}'::jsonb, :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {"tid": _TEST_TALENT_ID, "agency": str(_SENTINEL_AGENCY_ID)},
        )
        await s.commit()
    try:
        async with factory() as s:
            yield s
    finally:
        await engine.dispose()


def _items_sample() -> list[dict[str, Any]]:
    return [
        {
            "industry_id": "toys",
            "rationale": "Niche affinity (primary)",
            "source": "affinity_primary",
            "approved": True,
            "alternate_rationales": [],
        },
        {
            "industry_id": "grocery",
            "rationale": "Niche affinity (primary)",
            "source": "affinity_primary",
            "approved": True,
            "alternate_rationales": [],
        },
    ]


async def test_integration__create_pending__inserts_row(ir_session: Any) -> None:
    repo = IndustryReviewRepository(ir_session, agency_id=_SENTINEL_AGENCY_ID)
    review = await repo.create_pending(
        talent_id=_TEST_TALENT_ID, items=_items_sample(), search_run_id="run_001"
    )
    await ir_session.commit()
    assert review.status == "pending"
    assert review.search_run_id == "run_001"
    assert len(review.items) == 2


async def test_integration__create_pending__supersedes_prior_pending(ir_session: Any) -> None:
    """Creating a second pending review soft-rejects the first."""
    repo = IndustryReviewRepository(ir_session, agency_id=_SENTINEL_AGENCY_ID)
    first = await repo.create_pending(talent_id=_TEST_TALENT_ID, items=_items_sample())
    await ir_session.commit()
    second = await repo.create_pending(
        talent_id=_TEST_TALENT_ID,
        items=[
            {
                "industry_id": "auto-oems",
                "rationale": "Niche affinity (primary)",
                "source": "affinity_primary",
                "approved": True,
                "alternate_rationales": [],
            }
        ],
    )
    await ir_session.commit()

    # Pending lookup returns the new one.
    pending = await repo.get_pending(_TEST_TALENT_ID)
    assert pending is not None
    assert pending.review_id == second.review_id

    # The original is soft-deleted + rejected (no longer in the base filter).
    found_first = await repo.get_pending(_TEST_TALENT_ID)
    assert found_first is not None
    assert found_first.review_id != first.review_id


async def test_integration__patch_items__removes_flips_approval(ir_session: Any) -> None:
    repo = IndustryReviewRepository(ir_session, agency_id=_SENTINEL_AGENCY_ID)
    review = await repo.create_pending(talent_id=_TEST_TALENT_ID, items=_items_sample())
    await ir_session.commit()
    updated = await repo.patch_items(review.review_id, removed=["toys"])
    await ir_session.commit()
    toys = next(i for i in updated.items if i["industry_id"] == "toys")
    grocery = next(i for i in updated.items if i["industry_id"] == "grocery")
    assert toys["approved"] is False
    assert grocery["approved"] is True


async def test_integration__patch_items__added_creates_manual_entries(
    ir_session: Any,
) -> None:
    repo = IndustryReviewRepository(ir_session, agency_id=_SENTINEL_AGENCY_ID)
    review = await repo.create_pending(talent_id=_TEST_TALENT_ID, items=_items_sample())
    await ir_session.commit()
    updated = await repo.patch_items(
        review.review_id,
        added=[{"industry_id": "wearables", "rationale": "I want wearables"}],
    )
    await ir_session.commit()
    ids = {i["industry_id"] for i in updated.items}
    assert "wearables" in ids
    new_entry = next(i for i in updated.items if i["industry_id"] == "wearables")
    assert new_entry["source"] == "manual"
    assert new_entry["approved"] is True


async def test_integration__patch_items__already_approved_raises(ir_session: Any) -> None:
    repo = IndustryReviewRepository(ir_session, agency_id=_SENTINEL_AGENCY_ID)
    review = await repo.create_pending(talent_id=_TEST_TALENT_ID, items=_items_sample())
    await ir_session.commit()
    await repo.mark_approved(review.review_id)
    await ir_session.commit()
    with pytest.raises(BusinessRuleError):
        await repo.patch_items(review.review_id, removed=["toys"])


async def test_integration__mark_approved__sets_status_and_timestamp(
    ir_session: Any,
) -> None:
    repo = IndustryReviewRepository(ir_session, agency_id=_SENTINEL_AGENCY_ID)
    review = await repo.create_pending(talent_id=_TEST_TALENT_ID, items=_items_sample())
    await ir_session.commit()
    approved = await repo.mark_approved(review.review_id)
    await ir_session.commit()
    assert approved.status == "approved"
    assert approved.approved_at is not None


async def test_integration__get_by_id__missing_returns_none(ir_session: Any) -> None:
    repo = IndustryReviewRepository(ir_session, agency_id=_SENTINEL_AGENCY_ID)
    assert await repo.get_by_id("ir_does_not_exist") is None


async def test_integration__patch_items__missing_review_raises(ir_session: Any) -> None:
    repo = IndustryReviewRepository(ir_session, agency_id=_SENTINEL_AGENCY_ID)
    with pytest.raises(NotFoundError):
        await repo.patch_items("ir_does_not_exist", removed=["toys"])
