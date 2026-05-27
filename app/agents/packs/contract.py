"""``ContractPackAgent`` — Phase 4.7 contract pack coordinator skeleton.

Lands in M13.
"""

from __future__ import annotations

from app.agents.bundles import ContextBundle
from app.agents.coordinator import DealOrchestratorAgent
from app.agents.results import AgentResult


class ContractPackAgent(DealOrchestratorAgent):
    """Contract pack coordinator skeleton. Override lands in M13."""

    pack_type = "contract"

    async def _run_passes(self, bundle: ContextBundle) -> dict[str, AgentResult]:
        _ = bundle
        raise NotImplementedError("ContractPackAgent pack-specific pass sequence lands in M13.")

    async def _compose_bundle(self, deal_id: str) -> ContextBundle:
        _ = deal_id
        raise NotImplementedError("Bundle composer for contract lands in M13.")
