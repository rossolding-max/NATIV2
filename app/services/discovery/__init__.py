"""Phase 2 — Brand Discovery (M7) services package.

The 16 searches documented at ``docs/brand_discovery.md`` are independent
modules; the orchestrator runs the configured subset, merges results by
``brand_id``, scores each candidate, runs qualification + policy
filters, and writes both ``brand_candidate`` rows and the per-talent
JSON snapshot.

v0.1 ships Searches **1, 3, 5, 6, 7, 9, 10, 15** (the "Core 8"). The
remaining searches + the ``last30days`` skill that powers Search 16 are
deferred — see ``docs/brand_discovery.md`` § "M7 implementation notes".
"""

from app.services.discovery._models import (
    CandidateSource,
    DiscoveryRunResult,
    QualifiedCandidate,
)

__all__: tuple[str, ...] = (
    "CandidateSource",
    "DiscoveryRunResult",
    "QualifiedCandidate",
)
