"""Per-pack-type coordinator subclasses (M2+).

- ``DiscoveryPrepPackAgent`` (M2 example; M11 fleshes out)
- ``ProposalPackAgent`` (M12)
- ``ContractPackAgent`` (M13)
- ``InvoicePackAgent`` (M14)
- ``PerformanceReportPackAgent`` (M15)

Each is a thin subclass of ``DealOrchestratorAgent`` with the pack-specific
sequence in ``_run_passes`` + bundle composer in ``_compose_bundle``.
"""

from __future__ import annotations

from app.agents.packs.contract import ContractPackAgent
from app.agents.packs.discovery_prep import DiscoveryPrepPackAgent
from app.agents.packs.invoice import InvoicePackAgent
from app.agents.packs.performance_report import PerformanceReportPackAgent
from app.agents.packs.proposal import ProposalPackAgent

__all__ = [
    "ContractPackAgent",
    "DiscoveryPrepPackAgent",
    "InvoicePackAgent",
    "PerformanceReportPackAgent",
    "ProposalPackAgent",
]
