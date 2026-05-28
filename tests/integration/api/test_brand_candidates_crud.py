"""M7 Phase 2 brand-candidates REST surface integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from alembic import command

_SENTINEL_AGENCY_ID = UUID(int=0)
_TEST_TALENT_ID = "m7-test-talent"


@pytest.fixture
def _m7_setup_env(  # pyright: ignore[reportUnusedFunction]
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
async def m7_app(_m7_setup_env: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
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
                "TRUNCATE TABLE brand_candidate, brand_deal, talent_vault, talent, "
                "brand, agency_profile, memo CASCADE"
            )
        )
        # Seed a talent so the candidates have a referent.
        await s.execute(
            text(
                "INSERT INTO talent (talent_id, name, status, data, agency_id, "
                "created_at, updated_at, is_deleted) "
                "VALUES (:tid, :name, 'onboarding', :data, :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "tid": _TEST_TALENT_ID,
                "name": "M7 Talent",
                "data": json.dumps({"id": _TEST_TALENT_ID}),
                "agency": str(_SENTINEL_AGENCY_ID),
            },
        )
        # Seed a couple of brands for the candidate FKs.
        for slug, industry in [("gymshark", "activewear"), ("nike", "sportswear")]:
            await s.execute(
                text(
                    "INSERT INTO brand (brand_id, name, industry_id, data, "
                    "created_at, updated_at, is_deleted) "
                    "VALUES (:bid, :name, :iid, '{}', "
                    "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE) "
                    "ON CONFLICT (brand_id) DO NOTHING"
                ),
                {"bid": slug, "name": slug.capitalize(), "iid": industry},
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


async def _seed_candidate(
    db_session_factory: Any,
    *,
    brand_id: str = "gymshark",
    tier: str = "primary",
    status: str = "new",
    score: float = 0.55,
) -> str:
    from uuid import uuid4

    candidate_id = f"bc_{uuid4().hex[:24]}"
    async with db_session_factory() as s:
        await s.execute(
            text(
                "INSERT INTO brand_candidate (candidate_id, talent_id, brand_id, tier, "
                "status, score, data, agency_id, created_at, updated_at, is_deleted) "
                "VALUES (:cid, :tid, :bid, :tier, :st, :sc, :data, :agency, "
                "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC', FALSE)"
            ),
            {
                "cid": candidate_id,
                "tid": _TEST_TALENT_ID,
                "bid": brand_id,
                "tier": tier,
                "st": status,
                "sc": score,
                "data": json.dumps(
                    {
                        "brand": brand_id.capitalize(),
                        "brand_id": brand_id,
                        "industry_id": "activewear",
                        "score": score,
                        "tier": tier,
                        "status": status,
                    }
                ),
                "agency": str(_SENTINEL_AGENCY_ID),
            },
        )
        await s.commit()
    return candidate_id


async def test_integration__list_brand_candidates__happy_path(m7_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    await _seed_candidate(async_session_factory, brand_id="gymshark", tier="primary")
    await _seed_candidate(async_session_factory, brand_id="nike", tier="secondary")

    r_all = await m7_app.get(f"/api/v1/talents/{_TEST_TALENT_ID}/brand-candidates")
    assert r_all.status_code == 200, r_all.text
    assert len(r_all.json()["data"]) == 2

    r_filtered = await m7_app.get(
        f"/api/v1/talents/{_TEST_TALENT_ID}/brand-candidates?tier=primary"
    )
    rows = r_filtered.json()["data"]
    assert len(rows) == 1
    assert rows[0]["brand_id"] == "gymshark"


async def test_integration__get_brand_candidate_by_id(m7_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    candidate_id = await _seed_candidate(async_session_factory)
    r = await m7_app.get(f"/api/v1/brand-candidates/{candidate_id}")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["candidate_id"] == candidate_id


async def test_integration__patch_workflow_state(m7_app: AsyncClient) -> None:
    from app.db.session import async_session_factory

    candidate_id = await _seed_candidate(async_session_factory)
    r = await m7_app.patch(
        f"/api/v1/brand-candidates/{candidate_id}",
        json={"status": "shortlisted", "user_notes": "Saw their last campaign."},
    )
    assert r.status_code == 200, r.text
    body = r.json()["data"]
    assert body["status"] == "shortlisted"
    assert body["data"]["user_notes"].startswith("Saw")


async def test_integration__trigger_brand_discovery_run_202(m7_app: AsyncClient) -> None:
    """Manual rerun enqueues the Celery task and returns 202."""
    # Patch the celery send_task so we don't try to hit a real broker.
    with patch("app.celery_app.app.send_task", return_value=None) as mock_send:
        r = await m7_app.post(f"/api/v1/talents/{_TEST_TALENT_ID}/brand-discovery/run")
    assert r.status_code == 202, r.text
    body = r.json()["data"]
    assert body["enqueued"] is True
    assert body["enabled_searches"] is None  # omitted -> run all (the default)
    mock_send.assert_called_once()
    # Celery args: [talent_id, agency_id, enabled_searches]. Without an
    # agency bound to the request, agency_id falls back to the zero UUID.
    sent_args = mock_send.call_args.kwargs.get("args")
    assert sent_args == [_TEST_TALENT_ID, str(_SENTINEL_AGENCY_ID), None]


async def test_integration__trigger_run__with_search_subset(m7_app: AsyncClient) -> None:
    """POST body with ``searches`` narrows the Celery task arg."""
    with patch("app.celery_app.app.send_task", return_value=None) as mock_send:
        r = await m7_app.post(
            f"/api/v1/talents/{_TEST_TALENT_ID}/brand-discovery/run",
            json={"searches": ["search_1_reengagement", "search_5_primary_industry"]},
        )
    assert r.status_code == 202, r.text
    body = r.json()["data"]
    assert body["enabled_searches"] == ["search_1_reengagement", "search_5_primary_industry"]
    sent_args = mock_send.call_args.kwargs.get("args")
    assert sent_args == [
        _TEST_TALENT_ID,
        str(_SENTINEL_AGENCY_ID),
        ["search_1_reengagement", "search_5_primary_industry"],
    ]


async def test_integration__trigger_run__unknown_search_name_422(m7_app: AsyncClient) -> None:
    r = await m7_app.post(
        f"/api/v1/talents/{_TEST_TALENT_ID}/brand-discovery/run",
        json={"searches": ["search_1_reengagement", "search_99_typo"]},
    )
    assert r.status_code == 422, r.text
    payload = r.json()
    # The error envelope echoes the unknown names so a UI can highlight them.
    assert any("search_99_typo" in str(e) for e in payload.get("errors") or [])


async def test_integration__trigger_run__empty_searches_list_422(m7_app: AsyncClient) -> None:
    """Empty list is a probable client bug — reject with 422 rather than silently no-op."""
    r = await m7_app.post(
        f"/api/v1/talents/{_TEST_TALENT_ID}/brand-discovery/run",
        json={"searches": []},
    )
    assert r.status_code == 422, r.text


async def test_integration__trigger_run__dedupes_repeated_searches(m7_app: AsyncClient) -> None:
    """If a caller passes the same search twice we collapse to a single run entry."""
    with patch("app.celery_app.app.send_task", return_value=None) as mock_send:
        r = await m7_app.post(
            f"/api/v1/talents/{_TEST_TALENT_ID}/brand-discovery/run",
            json={"searches": ["search_1_reengagement", "search_1_reengagement"]},
        )
    assert r.status_code == 202, r.text
    sent_args = mock_send.call_args.kwargs.get("args")
    assert sent_args == [_TEST_TALENT_ID, str(_SENTINEL_AGENCY_ID), ["search_1_reengagement"]]


async def test_integration__discovery_searches_catalog(m7_app: AsyncClient) -> None:
    """The catalog endpoint lists all 16 searches with name/label/description/weight."""
    r = await m7_app.get("/api/v1/brand-discovery/searches")
    assert r.status_code == 200, r.text
    items = r.json()["data"]
    assert len(items) == 16
    names = [i["name"] for i in items]
    assert "search_1_reengagement" in names
    assert "search_16_last30days_trending" in names
    by_name = {i["name"]: i for i in items}
    assert by_name["search_13_values_aligned"]["requires_llm"] is True
    assert by_name["search_16_last30days_trending"]["requires_external_skill"] is True


async def test_integration__trigger_run__missing_talent_404(m7_app: AsyncClient) -> None:
    r = await m7_app.post("/api/v1/talents/no-such/brand-discovery/run")
    assert r.status_code == 404


async def test_integration__get_candidate__missing_404(m7_app: AsyncClient) -> None:
    r = await m7_app.get("/api/v1/brand-candidates/bc_does_not_exist")
    assert r.status_code == 404
