"""Step 9 / M7 — background brand-discovery kickoff (Celery task).

Fires from ``POST /api/v1/talents/{id}/activate`` (M5) and from the new
``POST /api/v1/talents/{id}/brand-discovery/run`` endpoint. Runs the
M7 discovery orchestrator, upserts the resulting ``brand_candidate``
rows, and writes the per-talent JSON snapshot.

Fire-and-forget — the calling endpoint must NOT block on this.
"""

from __future__ import annotations

from typing import Any

from asgiref.sync import async_to_sync

from app.celery_app import app as celery_app
from app.utils.logging import get_logger

log = get_logger(__name__)


async def _kick_off_async(
    talent_id: str,
    enabled_searches: list[str] | None = None,
) -> dict[str, Any]:
    """Run the M7 pipeline + persist results (DB + JSON snapshot)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import engine
    from app.repositories.brand_candidate import BrandCandidateRepository
    from app.repositories.brand_deal import BrandDealRepository
    from app.repositories.talent import TalentRepository
    from app.services.discovery.orchestrator import run_discovery
    from app.services.discovery.snapshot import _candidate_to_dict, write_snapshot

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        talents = TalentRepository(session)
        deals = BrandDealRepository(session)
        candidates_repo = BrandCandidateRepository(session)

        talent_row = await talents.get_by_talent_id(talent_id)
        if talent_row is None:
            log.warning("brand_discovery_talent_missing", talent_id=talent_id)
            return {"talent_id": talent_id, "status": "talent_missing"}

        deal_rows = await deals.find_by_talent(talent_id, limit=500)
        brand_deals = [dict(d.data or {}) for d in deal_rows]

        result = await run_discovery(
            talent_id=talent_id,
            talent_data=dict(talent_row.data or {}),
            brand_deals=brand_deals,
            enabled_searches=tuple(enabled_searches) if enabled_searches else None,
        )

        # Persist DB rows for kept candidates (blocked stay in JSON snapshot only).
        payloads = [_candidate_to_dict(c) for c in result.candidates]
        await candidates_repo.upsert_run_batch(talent_id, payloads, agency_id=talent_row.agency_id)
        await session.commit()

    snapshot_path = write_snapshot(result)

    log.info(
        "brand_discovery_run_complete",
        talent_id=talent_id,
        search_run_id=result.search_run_id,
        candidates=len(result.candidates),
        blocked=len(result.blocked),
        snapshot=str(snapshot_path),
    )
    return {
        "talent_id": talent_id,
        "search_run_id": result.search_run_id,
        "candidates": len(result.candidates),
        "blocked": len(result.blocked),
        "searches_run": result.searches_run,
        "errors": result.errors,
    }


@celery_app.task(name="app.services.talent_background_research.kick_off_brand_discovery")
def kick_off_brand_discovery(
    talent_id: str,
    enabled_searches: list[str] | None = None,
) -> dict[str, Any]:
    """Celery entry point — bridges async to sync via ``async_to_sync``.

    M5 shipped the stub; M7 replaces the body with the real pipeline.
    M7.1 added the optional ``enabled_searches`` arg — None/missing runs
    every search in the catalog; a list narrows the run. Same task name
    keeps M5 callers (which only pass ``talent_id``) working unchanged.
    """
    return async_to_sync(_kick_off_async)(talent_id, enabled_searches)
