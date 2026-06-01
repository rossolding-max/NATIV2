"""Step 9 / M7 — background brand-discovery kickoff (Celery task).

Fires from ``POST /api/v1/talents/{id}/activate`` (M5) and from the new
``POST /api/v1/talents/{id}/brand-discovery/run`` endpoint. Runs the
M7 discovery orchestrator, upserts the resulting ``brand_candidate``
rows, and writes the per-talent JSON snapshot.

Fire-and-forget — the calling endpoint must NOT block on this.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync

from app.celery_app import app as celery_app
from app.utils.logging import get_logger

log = get_logger(__name__)


async def _kick_off_async(
    talent_id: str,
    agency_id: str | None = None,
    enabled_searches: list[str] | None = None,
) -> dict[str, Any]:
    """Run the M7 pipeline + persist results (DB + JSON snapshot)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import engine
    from app.models.sqla.brand import Brand
    from app.repositories.brand import BrandRepository
    from app.repositories.brand_candidate import BrandCandidateRepository
    from app.repositories.brand_deal import BrandDealRepository
    from app.repositories.talent import TalentRepository
    from app.services.discovery._discovered_writer import append_discovered_brands
    from app.services.discovery.orchestrator import run_discovery
    from app.services.discovery.snapshot import _candidate_to_dict, write_snapshot

    # async_to_sync spins a fresh event loop per task invocation; the
    # SQLAlchemy async engine's pool keeps connections bound to the
    # previous (now-closed) loop. Drop them so the next checkout binds
    # to THIS task's loop.
    await engine.dispose()

    # The caller (REST trigger or /activate) passes the request-scoped
    # agency UUID; fall back to the zero sentinel for single-tenant deploys
    # where no agency is bound.
    agency_uuid = UUID(agency_id) if agency_id else UUID(int=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        talents = TalentRepository(session, agency_id=agency_uuid)
        deals = BrandDealRepository(session, agency_id=agency_uuid)
        candidates_repo = BrandCandidateRepository(session, agency_id=agency_uuid)

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

        # M7.3 — Search 15 / 18 (Exa-driven) emit candidates for net-new
        # brands not yet in the brand catalogue. Tier="emerging" sails
        # through qualification's promoted floor, but the FK on
        # brand_candidate.brand_id then fails because there's no Brand
        # row. Auto-create a minimal stub for each missing brand so the
        # upsert can land. Real seed-map writeback (with full attribute
        # enrichment) happens out-of-band per the "pending_writeback" log
        # line each search already emits.
        brands_repo = BrandRepository(session, agency_id=agency_uuid)
        for cand in result.candidates:
            # M7.5 — propagate domain + social handles onto the Brand stub
            # so downstream pipelines (contact enrichment, brand_deals)
            # have them without re-extracting.
            stub_data: dict[str, Any] = {
                "source": "exa_discovery",
                "first_surfaced_in_run": result.search_run_id,
            }
            if cand.domain:
                stub_data["domain"] = cand.domain
            if cand.social_handles:
                stub_data["social_handles"] = cand.social_handles
            # M7.7 — first-class brand metadata on the Brand DB row.
            if cand.sub_industry_id:
                stub_data["sub_industry_id"] = cand.sub_industry_id
            if cand.brand_category:
                stub_data["brand_category"] = cand.brand_category
            stub = Brand(
                brand_id=cand.brand_id,
                name=cand.brand_name,
                industry_id=cand.industry_id,
                data=stub_data,
            )
            await brands_repo.create_or_skip(stub)

        # Persist DB rows for kept candidates (blocked stay in JSON snapshot only).
        payloads = [_candidate_to_dict(c) for c in result.candidates]
        await candidates_repo.upsert_run_batch(talent_id, payloads, agency_id=talent_row.agency_id)
        await session.commit()

    # M7.4 — append net-new brands to brand_industry_map_discovered.json so
    # the next run for any talent in this agency surfaces them via Search
    # 5/6/7. Curated brand_industry_map.json wins on dedup.
    appended_brands = append_discovered_brands(payloads, search_run_id=result.search_run_id)

    snapshot_path = write_snapshot(result)

    log.info(
        "brand_discovery_run_complete",
        talent_id=talent_id,
        search_run_id=result.search_run_id,
        candidates=len(result.candidates),
        blocked=len(result.blocked),
        snapshot=str(snapshot_path),
        appended_to_discovered_seed_map=appended_brands,
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
    agency_id: str | None = None,
    enabled_searches: list[str] | None = None,
) -> dict[str, Any]:
    """Celery entry point — bridges async to sync via ``async_to_sync``.

    M5 shipped the stub; M7 replaces the body with the real pipeline.
    M7.1 added the optional ``enabled_searches`` arg. The smoke-test
    surfaced a second gap: the worker had no way to learn the
    request-scoped ``agency_id``, so it always fell back to the zero
    UUID and 404'd on agency-scoped talents. Both REST callers
    (``/activate`` + ``/brand-discovery/run``) now pass it explicitly.
    """
    return async_to_sync(_kick_off_async)(talent_id, agency_id, enabled_searches)


# ── M7.7 v2 Phase 2 task ──────────────────────────────────────────


async def _phase_2_async(
    talent_id: str,
    agency_id: str | None,
    review_id: str,
) -> dict[str, Any]:
    """Run v2 Phase 2 + 3 + 4 against the approved IndustryReview."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import engine
    from app.models.sqla.brand import Brand
    from app.repositories.brand import BrandRepository
    from app.repositories.brand_candidate import BrandCandidateRepository
    from app.repositories.brand_deal import BrandDealRepository
    from app.repositories.industry_review import IndustryReviewRepository
    from app.repositories.talent import TalentRepository
    from app.services.discovery._discovered_writer import append_discovered_brands
    from app.services.discovery.orchestrator import run_discovery_v2_phase_2
    from app.services.discovery.snapshot import _candidate_to_dict, write_snapshot

    await engine.dispose()
    agency_uuid = UUID(agency_id) if agency_id else UUID(int=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        talents = TalentRepository(session, agency_id=agency_uuid)
        deals = BrandDealRepository(session, agency_id=agency_uuid)
        candidates_repo = BrandCandidateRepository(session, agency_id=agency_uuid)
        reviews = IndustryReviewRepository(session, agency_id=agency_uuid)

        talent_row = await talents.get_by_talent_id(talent_id)
        if talent_row is None:
            log.warning("v2_phase_2_talent_missing", talent_id=talent_id)
            return {"talent_id": talent_id, "status": "talent_missing"}

        review = await reviews.get_by_id(review_id)
        if review is None or review.status != "approved":
            log.warning(
                "v2_phase_2_review_not_approved",
                review_id=review_id,
                status=getattr(review, "status", None),
            )
            return {
                "talent_id": talent_id,
                "review_id": review_id,
                "status": "review_not_approved",
            }

        approved_industries: list[str] = []
        for item in review.items or []:
            if not item or not item.get("approved"):
                continue
            iid = item.get("industry_id")
            if isinstance(iid, str) and iid:
                approved_industries.append(iid)

        deal_rows = await deals.find_by_talent(talent_id, limit=500)
        brand_deals = [dict(d.data or {}) for d in deal_rows]

        from app.config import settings as _settings

        result = await run_discovery_v2_phase_2(
            talent_id=talent_id,
            talent_data=dict(talent_row.data or {}),
            brand_deals=brand_deals,
            approved_industries=approved_industries,
            values_search_enabled=bool(_settings.discovery_values_search_default_themes)
            or bool(
                (talent_row.data or {}).get("brand_preferences", {}).get("values_aligned_themes")
            ),
        )

        brands_repo = BrandRepository(session, agency_id=agency_uuid)
        for cand in result.candidates:
            stub_data: dict[str, Any] = {
                "source": "v2_phase_2",
                "first_surfaced_in_run": result.search_run_id,
            }
            if cand.domain:
                stub_data["domain"] = cand.domain
            if cand.social_handles:
                stub_data["social_handles"] = cand.social_handles
            if cand.sub_industry_id:
                stub_data["sub_industry_id"] = cand.sub_industry_id
            if cand.brand_category:
                stub_data["brand_category"] = cand.brand_category
            stub = Brand(
                brand_id=cand.brand_id,
                name=cand.brand_name,
                industry_id=cand.industry_id,
                data=stub_data,
            )
            await brands_repo.create_or_skip(stub)

        payloads = [_candidate_to_dict(c) for c in result.candidates]
        await candidates_repo.upsert_run_batch(talent_id, payloads, agency_id=talent_row.agency_id)
        await session.commit()

    appended_brands = append_discovered_brands(payloads, search_run_id=result.search_run_id)
    snapshot_path = write_snapshot(result)

    log.info(
        "v2_phase_2_run_complete",
        talent_id=talent_id,
        review_id=review_id,
        search_run_id=result.search_run_id,
        candidates=len(result.candidates),
        approved_industry_count=len(approved_industries),
        snapshot=str(snapshot_path),
        appended_to_discovered_seed_map=appended_brands,
    )
    return {
        "talent_id": talent_id,
        "review_id": review_id,
        "search_run_id": result.search_run_id,
        "candidates": len(result.candidates),
        "blocked": len(result.blocked),
        "approved_industry_count": len(approved_industries),
        "errors": result.errors,
    }


@celery_app.task(name="app.services.talent_background_research.kick_off_phase_2_brand_universe")
def kick_off_phase_2_brand_universe(
    talent_id: str,
    agency_id: str | None = None,
    review_id: str = "",
) -> dict[str, Any]:
    """Celery entry point for M7.7 Phase 2 (full_build mode, post-approval)."""
    return async_to_sync(_phase_2_async)(talent_id, agency_id, review_id)
