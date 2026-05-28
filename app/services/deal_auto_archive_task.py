"""15-minute Celery beat task — auto-archive deals once all 3 gates pass.

The 3 archive gates per ``docs/deal_lifecycle_workflow.md``:

1. ``data.close.all_invoices_paid_at`` IS NOT NULL
2. ``data.close.final_kpis`` IS NOT NULL
3. ``data.close.final_performance_report_attachment_id`` IS NOT NULL

When all three are satisfied, transition ``post_campaign_reporting`` ->
``archived`` (which the state machine flips to ``is_terminal=True`` +
``is_won=True``). ``DealRepository.find_ready_for_archive`` already
filters on substage + gates.

The corresponding ``brand_deal`` closing write loops back to M6's history
table — that ships in M16, not here. This task only handles the
deal-level archive transition.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync

from app.celery_app import app as celery_app
from app.repositories.deal import DealRepository
from app.services.deal_lifecycle import orchestrator
from app.utils.logging import get_logger

log = get_logger(__name__)

# Cap per tick so a backlog can't archive thousands at once.
_PER_TICK_CAP = 50


async def process_ready_archives(
    repo: DealRepository,
    *,
    limit: int = _PER_TICK_CAP,
) -> dict[str, Any]:
    """Pure helper — transition every deal whose 3 gates are satisfied.

    Caller owns the session + commit. The orchestrator mutates each
    deal in place; we let the caller flush.
    """
    ready = await repo.find_ready_for_archive(limit=limit)
    archived = 0
    errors: list[str] = []

    for deal in ready:
        try:
            orchestrator.apply_transition(
                deal=deal,
                target_substage="archived",
                by_agent_id="system_auto_archive",
                note="all 3 close-gate checks passed",
            )
        except Exception as exc:
            errors.append(f"deal={deal.deal_id}: {exc!s}")
            continue
        archived += 1

    return {"status": "ok", "archived": archived, "errors": errors}


async def _run_async(agency_id: str | None = None) -> dict[str, Any]:
    """Bootstrap — open session, wire repo, delegate to ``process_ready_archives``."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import engine

    await engine.dispose()
    agency_uuid = UUID(agency_id) if agency_id else UUID(int=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        repo = DealRepository(session, agency_id=agency_uuid)
        result = await process_ready_archives(repo)
        if result["archived"]:
            await session.flush()
        await session.commit()

    log.info(
        "auto_archive_trigger_check_complete",
        archived=result["archived"],
        errors=len(result["errors"]),
    )
    return result


@celery_app.task(name="app.services.deal_auto_archive_task.auto_archive_trigger_check")
def auto_archive_trigger_check(agency_id: str | None = None) -> dict[str, Any]:
    """Celery beat entry point — runs every 15 minutes."""
    return async_to_sync(_run_async)(agency_id)
