"""M7.7 — Phase 1.5 industry-review REST surface integration tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from alembic import command

_SENTINEL_AGENCY_ID = UUID(int=0)
_TEST_TALENT_ID = "ir-rest-talent"


@pytest.fixture
def _m77_setup_env(  # pyright: ignore[reportUnusedFunction]
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
async def m77_app(_m77_setup_env: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import settings as live_settings
    from app.db import session as db_session

    new_engine = create_async_engine(live_settings.database_url_async, future=True)
    new_factory = async_sessionmaker(new_engine, expire_on_commit=False)
    original_engine = db_session.engine
    original_factory = db_session.async_session_factory
    db_session.engine = new_engine
    db_session.async_session_factory = new_factory

    async with new_factory() as s:
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
        from app.main import app

        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
        ):
            yield client
    finally:
        await new_engine.dispose()
        db_session.engine = original_engine
        db_session.async_session_factory = original_factory


async def _seed_pending_review(items: list[dict[str, Any]]) -> str:
    """Insert a pending IndustryReview row directly via the repo."""
    from app.db.session import async_session_factory
    from app.repositories.industry_review import IndustryReviewRepository

    async with async_session_factory() as s:
        repo = IndustryReviewRepository(s, agency_id=_SENTINEL_AGENCY_ID)
        review = await repo.create_pending(
            talent_id=_TEST_TALENT_ID, items=items, search_run_id=f"run_{uuid4().hex[:8]}"
        )
        await s.commit()
        return str(review.review_id)


def _sample_items() -> list[dict[str, Any]]:
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


async def test_integration__get_industry_review__happy_path(m77_app: AsyncClient) -> None:
    await _seed_pending_review(_sample_items())
    r = await m77_app.get(f"/api/v1/talents/{_TEST_TALENT_ID}/industry-review")
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "pending"
    assert {i["industry_id"] for i in body["items"]} == {"toys", "grocery"}


async def test_integration__get_industry_review__no_pending_404(m77_app: AsyncClient) -> None:
    r = await m77_app.get(f"/api/v1/talents/{_TEST_TALENT_ID}/industry-review")
    assert r.status_code == 404


async def test_integration__patch_industry_review__removes_industry(
    m77_app: AsyncClient,
) -> None:
    await _seed_pending_review(_sample_items())
    r = await m77_app.patch(
        f"/api/v1/talents/{_TEST_TALENT_ID}/industry-review",
        json={"removed": ["toys"]},
    )
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    toys = next(i for i in items if i["industry_id"] == "toys")
    grocery = next(i for i in items if i["industry_id"] == "grocery")
    assert toys["approved"] is False
    assert grocery["approved"] is True


async def test_integration__patch_industry_review__adds_manual_entry(
    m77_app: AsyncClient,
) -> None:
    await _seed_pending_review(_sample_items())
    r = await m77_app.patch(
        f"/api/v1/talents/{_TEST_TALENT_ID}/industry-review",
        json={"added": [{"industry_id": "wearables", "rationale": "Manual add"}]},
    )
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    wearables = next(i for i in items if i["industry_id"] == "wearables")
    assert wearables["source"] == "manual"
    assert wearables["approved"] is True


async def test_integration__approve_industry_review__enqueues_phase_2(
    m77_app: AsyncClient,
) -> None:
    await _seed_pending_review(_sample_items())
    with patch("app.celery_app.app.send_task", return_value=None) as mock_send:
        r = await m77_app.post(f"/api/v1/talents/{_TEST_TALENT_ID}/industry-review/approve")
    assert r.status_code == 202, r.text
    body = r.json()["data"]
    assert body["status"] == "approved"
    assert body["phase_2_enqueued"] is True
    assert body["approved_industry_count"] == 2
    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args.kwargs
    sent_args = call_kwargs.get("args") or []
    assert sent_args[0] == _TEST_TALENT_ID  # talent_id is the first positional arg


async def test_integration__approve_twice__second_returns_404(m77_app: AsyncClient) -> None:
    """Once approved the pending record is gone; the second approve has nothing to act on."""
    await _seed_pending_review(_sample_items())
    with patch("app.celery_app.app.send_task", return_value=None):
        r1 = await m77_app.post(f"/api/v1/talents/{_TEST_TALENT_ID}/industry-review/approve")
        assert r1.status_code == 202
        r2 = await m77_app.post(f"/api/v1/talents/{_TEST_TALENT_ID}/industry-review/approve")
        assert r2.status_code == 404
