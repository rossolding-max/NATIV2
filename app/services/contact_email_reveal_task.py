"""M8.1 — Celery task wrapping the Step 5b bulk-reveal flow.

Fires from ``POST /api/v1/brands/{brand_id}/contact-emails/reveal``
when the operator submits a list of contact_ids. The task fans out
to Apollo ``/people/match`` per contact (sequential — Apollo has no
bulk endpoint; the global 60/min rate-limit applies), applies the
strict-honesty floor per row, and writes ``email`` + ``revealed_at``
+ ``verification_status`` back to ``brand_contact``.

Follows the celery-worker-bootstrap rules (memory
[[feedback-celery-worker-bootstrap]]):
  - registered in ``celery_app.include=``
  - accepts ``agency_id`` arg
  - inits taxonomies per fork (no-op here — no taxonomy use)
  - calls ``engine.dispose()`` per task body so the async engine
    rebinds to this task's event loop
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync

from app.celery_app import app as celery_app
from app.utils.logging import get_logger

log = get_logger(__name__)


async def _reveal_async(
    brand_id: str,
    contact_ids: list[str],
    agency_id: str,
) -> dict[str, Any]:
    """Run Step 5b reveal for ``contact_ids`` against ``brand_id``."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import engine
    from app.repositories.brand import BrandRepository
    from app.repositories.brand_contact import BrandContactRepository
    from app.services.contact_enrichment.step_5b_reveal_email import (
        reveal_emails_for_contacts,
    )

    await engine.dispose()
    agency_uuid = UUID(agency_id)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        brands = BrandRepository(session, agency_id=agency_uuid)
        contacts_repo = BrandContactRepository(session, agency_id=agency_uuid)

        brand_row = await brands.get_by_id(brand_id)
        if brand_row is None:
            log.warning("reveal_brand_missing", brand_id=brand_id)
            return {"brand_id": brand_id, "status": "brand_missing"}

        results = await reveal_emails_for_contacts(
            brand_id=brand_id,
            contact_ids=contact_ids,
            agency_id=agency_uuid,
            repo=contacts_repo,
            brand_domain=brand_row.domain,
        )
        await session.commit()

    revealed = sum(1 for r in results if r.get("email_revealed"))
    log.info(
        "reveal_contact_emails_complete",
        brand_id=brand_id,
        requested=len(contact_ids),
        revealed=revealed,
        not_revealed=len(results) - revealed,
    )
    return {
        "brand_id": brand_id,
        "requested": len(contact_ids),
        "revealed": revealed,
        "results": results,
    }


@celery_app.task(name="app.services.contact_email_reveal_task.reveal_contact_emails")
def reveal_contact_emails(
    brand_id: str,
    contact_ids: list[str],
    agency_id: str,
) -> dict[str, Any]:
    """Celery entry point — bridges async to sync via ``async_to_sync``."""
    return async_to_sync(_reveal_async)(brand_id, contact_ids, agency_id)
