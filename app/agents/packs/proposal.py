"""``ProposalPackAgent`` — Phase 4.6 proposal pack coordinator skeleton.

Lands in M12. Until then, ``.run(deal_id)`` raises NotImplementedError.
"""

from __future__ import annotations

from app.agents.bundles import ContextBundle
from app.agents.coordinator import DealOrchestratorAgent
from app.agents.results import AgentResult


class ProposalPackAgent(DealOrchestratorAgent):
    """Proposal pack coordinator skeleton. Override lands in M12."""

    pack_type = "proposal"

    async def _run_passes(self, bundle: ContextBundle) -> dict[str, AgentResult]:
        _ = bundle
        raise NotImplementedError("ProposalPackAgent pack-specific pass sequence lands in M12.")

    async def _compose_bundle(self, deal_id: str) -> ContextBundle:
        _ = deal_id
        raise NotImplementedError("Bundle composer for proposal lands in M12.")
