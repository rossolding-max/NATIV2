"""``InvoicePackAgent`` — Phase 4.8 invoice pack coordinator skeleton.

Lands in M14.
"""

from __future__ import annotations

from app.agents.bundles import ContextBundle
from app.agents.coordinator import DealOrchestratorAgent
from app.agents.results import AgentResult


class InvoicePackAgent(DealOrchestratorAgent):
    """Invoice pack coordinator skeleton. Override lands in M14."""

    pack_type = "invoice"

    async def _run_passes(self, bundle: ContextBundle) -> dict[str, AgentResult]:
        _ = bundle
        raise NotImplementedError("InvoicePackAgent pack-specific pass sequence lands in M14.")

    async def _compose_bundle(self, deal_id: str) -> ContextBundle:
        _ = deal_id
        raise NotImplementedError("Bundle composer for invoice lands in M14.")
