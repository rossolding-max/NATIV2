"""``DiscoveryPrepPackAgent`` — Phase 4.5 discovery prep pack coordinator.

M2 example implementation. Inherits the base ``DealOrchestratorAgent`` with
``pack_type="discovery_prep"`` and the default researcher → writer sequence.

M11 (the discovery prep milestone) refines:
- 3-pass writer (briefing → agenda → slides) instead of M2's single
  briefing pass.
- Exa research integration via the researcher's ``exa_search`` tool.
- S3-or-filesystem pack artefact persistence + Postgres pack row writes.
- Schema validation against ``discovery_prep_pack.schema.json`` before return.
"""

from __future__ import annotations

from app.agents.coordinator import DealOrchestratorAgent


class DiscoveryPrepPackAgent(DealOrchestratorAgent):
    """Discovery prep pack coordinator. M2 example; M11 fleshes out."""

    pack_type = "discovery_prep"
