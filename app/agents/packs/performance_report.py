"""``PerformanceReportPackAgent`` — Phase 4.9 performance report skeleton.

Lands in M15.
"""

from __future__ import annotations

from app.agents.bundles import ContextBundle
from app.agents.coordinator import DealOrchestratorAgent
from app.agents.results import AgentResult


class PerformanceReportPackAgent(DealOrchestratorAgent):
    """Performance report coordinator skeleton. Override lands in M15."""

    pack_type = "performance_report"

    async def _run_passes(self, bundle: ContextBundle) -> dict[str, AgentResult]:
        _ = bundle
        raise NotImplementedError(
            "PerformanceReportPackAgent pack-specific pass sequence lands in M15."
        )

    async def _compose_bundle(self, deal_id: str) -> ContextBundle:
        _ = deal_id
        raise NotImplementedError("Bundle composer for performance_report lands in M15.")
