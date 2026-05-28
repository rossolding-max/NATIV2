"""M8 — Celery task body wrapping the contact-enrichment orchestrator.

Fires from ``POST /api/v1/brands/{brand_id}/contact-enrichment/run``
(manual trigger only in v0.1). Runs the M8 orchestrator, upserts
``brand_contact`` rows, writes the per-brand JSON snapshot.

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
    brand_id: str,
    agency_id: str,
    talent_id: str | None = None,
    target_titles: list[str] | None = None,
) -> dict[str, Any]:
    """Run the M8 pipeline + persist results (DB + JSON snapshot)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import engine
    from app.repositories.brand import BrandRepository
    from app.repositories.brand_contact import BrandContactRepository
    from app.services.contact_enrichment.orchestrator import run_enrichment
    from app.services.contact_enrichment.snapshot import _contact_to_dict, write_snapshot

    agency_uuid = UUID(agency_id)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        brands = BrandRepository(session, agency_id=agency_uuid)
        contacts_repo = BrandContactRepository(session, agency_id=agency_uuid)

        brand_row = await brands.get_by_id(brand_id)
        if brand_row is None:
            log.warning("contact_enrichment_brand_missing", brand_id=brand_id)
            return {"brand_id": brand_id, "status": "brand_missing"}

        brand_metadata = {
            "name": brand_row.name,
            "domain": brand_row.domain,
            "industry_id": brand_row.industry_id,
            "company_stage": brand_row.company_stage,
            "typical_campaign_tier": brand_row.typical_campaign_tier,
            **(dict(brand_row.data or {})),
        }

        # Load existing workflow state for the DNC + cooldown checks.
        existing_rows = await contacts_repo.find_by_brand(brand_id)
        existing_workflow: dict[str, dict[str, Any]] = {
            r.contact_id: {
                "do_not_contact": r.do_not_contact,
                **(dict(r.data or {})),
            }
            for r in existing_rows
        }

        result = await run_enrichment(
            brand_id=brand_id,
            brand_metadata=brand_metadata,
            talent_id=talent_id,
            target_titles=target_titles,
            existing_workflow=existing_workflow,
        )

        # Persist kept contacts; blocked stay in the JSON snapshot only.
        payloads = [_contact_to_dict(c) for c in result.contacts]
        await contacts_repo.upsert_run_batch(brand_id, payloads, agency_id=agency_uuid)
        await session.commit()

    snapshot_path = write_snapshot(result)

    log.info(
        "contact_enrichment_run_complete",
        brand_id=brand_id,
        run_id=result.run_id,
        contacts=len(result.contacts),
        blocked=len(result.blocked),
        snapshot=str(snapshot_path),
    )
    return {
        "brand_id": brand_id,
        "run_id": result.run_id,
        "contacts": len(result.contacts),
        "blocked": len(result.blocked),
        "steps_run": result.steps_run,
        "errors": result.errors,
    }


@celery_app.task(name="app.services.contact_enrichment_task.kick_off_contact_enrichment")
def kick_off_contact_enrichment(
    brand_id: str,
    agency_id: str,
    talent_id: str | None = None,
    target_titles: list[str] | None = None,
) -> dict[str, Any]:
    """Celery entry point — bridges async to sync via ``async_to_sync``."""
    return async_to_sync(_kick_off_async)(brand_id, agency_id, talent_id, target_titles)
