"""5-minute Celery beat task — enqueue Discovery Prep Pack generation.

Walks ``deal.substage == 'initial_call_scheduled'`` rows whose
``latest_prep_pack_id`` is still NULL and enqueues the generic
``app.tasks.pack_generation.generate_pack`` dispatcher with
``pack_type="discovery_prep"``. M10 only enqueues; M11 ships the actual
researcher + writer subagent chain.

Debounces on ``data.prep_pack_enqueued_at`` (set when we enqueue) so the
5-min tick doesn't pile up duplicate jobs while M11's task is mid-flight.
``DealRepository.find_ready_for_prep_pack`` already filters on that stamp.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from asgiref.sync import async_to_sync

from app.celery_app import app as celery_app
from app.repositories.deal import DealRepository
from app.utils.logging import get_logger

log = get_logger(__name__)

# Cap per tick so a backlog can't flood ``llm_heavy`` in one go.
_PER_TICK_CAP = 50


class _SendTaskFn(Protocol):
    def __call__(self, name: str, *, kwargs: dict[str, Any]) -> Any: ...


async def process_ready_deals(
    repo: DealRepository,
    *,
    send_task: _SendTaskFn,
    now: datetime,
    limit: int = _PER_TICK_CAP,
) -> dict[str, Any]:
    """Pure helper — load ready deals, enqueue prep-pack tasks, stamp debounce.

    Caller owns the session + commit; this helper just orchestrates
    repo reads, ``send_task`` calls, and the debounce-stamp write.
    """
    ready = await repo.find_ready_for_prep_pack(limit=limit)
    now_iso = now.isoformat()
    enqueued = 0
    errors: list[str] = []

    for deal in ready:
        try:
            send_task(
                "app.tasks.pack_generation.generate_pack",
                kwargs={
                    "pack_type": "discovery_prep",
                    "deal_id": deal.deal_id,
                    "agency_id": str(deal.agency_id),
                    "agent_id": "system",
                },
            )
        except Exception as exc:
            errors.append(f"deal={deal.deal_id}: {exc!s}")
            continue

        # Stamp the debounce marker so the next 5-min tick skips us
        # until either the pack lands (latest_prep_pack_id set by M11)
        # or 1 hour passes (find_ready_for_prep_pack retry window).
        data = dict(deal.data or {})
        data["prep_pack_enqueued_at"] = now_iso
        deal.data = data
        enqueued += 1

    return {"status": "ok", "enqueued": enqueued, "errors": errors}


async def _run_async(agency_id: str | None = None) -> dict[str, Any]:
    """Bootstrap — open session, wire repo, delegate to ``process_ready_deals``."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.db.session import engine

    await engine.dispose()
    agency_uuid = UUID(agency_id) if agency_id else UUID(int=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        repo = DealRepository(session, agency_id=agency_uuid)
        result = await process_ready_deals(
            repo, send_task=celery_app.send_task, now=datetime.now(UTC)
        )
        await session.commit()

    log.info(
        "phase_4_5_auto_fire_complete",
        enqueued=result["enqueued"],
        errors=len(result["errors"]),
    )
    return result


@celery_app.task(name="app.services.deal_phase_4_5_auto_fire_task.phase_4_5_auto_fire")
def phase_4_5_auto_fire(agency_id: str | None = None) -> dict[str, Any]:
    """Celery beat entry point — runs every 5 minutes."""
    return async_to_sync(_run_async)(agency_id)
