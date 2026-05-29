"""Celery task wrapper for pack generation.

Bridges Celery's sync execution model to the async ``DealOrchestratorAgent``
via ``asgiref.sync.async_to_sync`` (NOT ``asyncio.run`` per the M2 plan's
execution-time landmines section — ``asyncio.run`` closes the loop and the
next task on the same worker process fails).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync

from app.agents.bundles import PackType
from app.celery_app import app as celery_app
from app.db.session import async_session_factory
from app.utils.logging import get_logger

log = get_logger(__name__)


@celery_app.task(name="app.tasks.pack_generation.generate_pack", queue="llm_heavy")
def generate_pack(
    pack_type: str,
    deal_id: str,
    agency_id: str,
    agent_id: str,
    *,
    pre_generation_guidance: str | None = None,
    regeneration_feedback: str | None = None,
    parent_version: int | None = None,
) -> dict[str, Any]:
    """Generate a pack via the appropriate pack-specific coordinator.

    The ``pre_generation_guidance``, ``regeneration_feedback``, and
    ``parent_version`` kwargs are M11+ additions for discovery prep
    pack regen flows. Pack subclasses that accept them must declare
    them in their ``__init__``; the dispatcher only forwards them when
    the kwarg is non-None to keep older subclasses' signatures intact.
    """
    log.info(
        "pack_generation_celery_task_started",
        pack_type=pack_type,
        deal_id=deal_id,
        agent_id=agent_id,
        parent_version=parent_version,
    )

    async def _run() -> dict[str, Any]:
        from app.agents.packs import (
            ContractPackAgent,
            DiscoveryPrepPackAgent,
            InvoicePackAgent,
            PerformanceReportPackAgent,
            ProposalPackAgent,
        )

        agent_classes: dict[PackType, type] = {
            "discovery_prep": DiscoveryPrepPackAgent,
            "proposal": ProposalPackAgent,
            "contract": ContractPackAgent,
            "invoice": InvoicePackAgent,
            "performance_report": PerformanceReportPackAgent,
        }
        cls = agent_classes.get(pack_type)  # type: ignore[arg-type]
        if cls is None:
            raise ValueError(f"Unknown pack_type: {pack_type}")

        async with async_session_factory() as session:
            kwargs: dict[str, Any] = {
                "agency_id": UUID(agency_id),
                "agent_id": agent_id,
            }
            # Only thread M11 kwargs to subclasses that accept them.
            if pack_type == "discovery_prep":
                kwargs["pre_generation_guidance"] = pre_generation_guidance
                kwargs["regeneration_feedback"] = regeneration_feedback
                kwargs["parent_version"] = parent_version
            agent = cls(session, **kwargs)
            result = await agent.run(deal_id)
            await session.commit()
            return result.model_dump(mode="json")

    # async_to_sync preserves the event loop for the next task on the same
    # worker — asyncio.run would close it.
    return async_to_sync(_run)()
