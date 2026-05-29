"""M7.7 — Monthly Phase 4 signal-overlay cron.

Once a month, walks active talents (any deal closed in the last 90 days
OR any discovery run in the last 60 days) and enqueues a maintenance-mode
brand discovery run for each. The maintenance pipeline picks up Phase 4
(S15-global + S16 + S17), refreshing the signal layer without re-running
the expensive Phase 2 brand universe build.

The fan-out enqueues one ``kick_off_brand_discovery`` task per talent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from asgiref.sync import async_to_sync
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.celery_app import app as celery_app
from app.db.session import engine
from app.models.sqla.brand_candidate import BrandCandidate
from app.models.sqla.brand_deal import BrandDeal
from app.models.sqla.talent import Talent
from app.utils.logging import get_logger

log = get_logger(__name__)


async def _active_talent_ids() -> list[tuple[str, str]]:
    """Return (talent_id, agency_id) pairs for active talents.

    Active = deal closed within 90 days OR discovery run within 60 days.
    """
    await engine.dispose()
    factory = async_sessionmaker(engine, expire_on_commit=False)
    out: list[tuple[str, str]] = []
    async with factory() as session:
        ninety_days_ago = datetime.now(UTC) - timedelta(days=90)
        sixty_days_ago = datetime.now(UTC) - timedelta(days=60)

        deal_active = (
            select(BrandDeal.talent_id, BrandDeal.agency_id)
            .where(BrandDeal.created_at >= ninety_days_ago, BrandDeal.is_deleted.is_(False))
            .distinct()
        )
        discovery_active = (
            select(BrandCandidate.talent_id, BrandCandidate.agency_id)
            .where(
                BrandCandidate.created_at >= sixty_days_ago,
                BrandCandidate.is_deleted.is_(False),
            )
            .distinct()
        )
        # Union both signals.
        combined = (
            select(Talent.talent_id, Talent.agency_id)
            .where(
                Talent.is_deleted.is_(False),
                Talent.talent_id.in_(
                    select(deal_active.subquery().c.talent_id).union(
                        select(discovery_active.subquery().c.talent_id)
                    )
                ),
            )
            .distinct()
        )
        result = await session.execute(combined)
        for row in result.all():
            tid, aid = row
            out.append((str(tid), str(aid) if aid else ""))
    return out


async def _enqueue_phase_4_for_active() -> dict[str, Any]:
    """Walk active talents + enqueue a maintenance-mode discovery run for each."""
    talents = await _active_talent_ids()
    enqueued = 0
    for talent_id, agency_id in talents:
        try:
            celery_app.send_task(
                "app.services.talent_background_research.kick_off_brand_discovery",
                args=[talent_id, agency_id or None, None],
            )
            enqueued += 1
        except Exception as exc:
            log.warning(
                "phase_4_monthly_enqueue_failed",
                talent_id=talent_id,
                error=str(exc),
            )
    log.info("phase_4_monthly_run_complete", active_talents=len(talents), enqueued=enqueued)
    return {"active_talents": len(talents), "enqueued": enqueued}


@celery_app.task(name="app.services.discovery_phase_4_monthly.fan_out_to_active_talents")
def fan_out_to_active_talents() -> dict[str, Any]:
    """Celery beat entry point — runs monthly."""
    return async_to_sync(_enqueue_phase_4_for_active)()
