"""Shared dataclasses for the M7 discovery pipeline.

Each search returns a list of ``CandidateSource`` records. The
orchestrator groups them by ``brand_id``, builds a ``QualifiedCandidate``
per group with the score / tier / qualification / policy decision, and
wraps everything in a ``DiscoveryRunResult`` for the snapshot writer +
DB upsert.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass(frozen=True)
class CandidateSource:
    """One search-hit for a brand. Multiple sources can stack on the same brand."""

    brand_id: str
    brand_name: str
    industry_id: str
    search_tag: str
    weight: float
    note: str = ""
    # M7.5 — exact-query provenance for Exa-driven searches (S15 + S18).
    # Populated only when the source came from an Exa search; deterministic
    # searches (S1-S14) leave these None.
    exa_query: str | None = None
    exa_result_url: str | None = None
    exa_result_title: str | None = None
    # M7.5 — brand-level metadata extracted by the LLM from this source's
    # Exa result text. The orchestrator aggregates across all sources per
    # brand (first non-null wins) onto the QualifiedCandidate.
    brand_domain: str | None = None
    brand_social_handles: dict[str, str | None] | None = None


@dataclass
class QualifiedCandidate:
    """A merged + scored + qualified candidate ready to write to DB."""

    brand_id: str
    brand_name: str
    industry_id: str
    score: float
    tier: Literal["re-engage", "primary", "secondary", "tertiary", "emerging"]
    sources: list[CandidateSource]
    qualification_score: float
    qualification_tier: Literal["qualified", "speculative", "unqualified"]
    qualification_signals: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None
    # M7.5 — brand-level metadata aggregated across sources. Surfaces on
    # brand_candidate.data and gets written to brand_industry_map_discovered.
    domain: str | None = None
    social_handles: dict[str, str | None] | None = None
    # M7.7 — first-class brand metadata. industry_id above stays as the
    # leaf (sub-industry) for back-compat; these split it cleanly.
    sub_industry_id: str | None = None
    brand_category: Literal["emerging", "growth", "established"] | None = None


@dataclass
class DiscoveryRunResult:
    """Aggregate output of one discovery run."""

    talent_id: str
    search_run_id: str
    generated_at: datetime
    searches_run: list[str]
    candidates: list[QualifiedCandidate] = field(default_factory=list)
    blocked: list[QualifiedCandidate] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ── M7.7 v2 architecture ─────────────────────────────────────────


# Source label for an industry proposal — drives the priority order
# when dedup'ing the same industry surfaced by multiple sources.
# Order in this Literal == priority (first wins on dedup).
IndustryProposalSource = Literal[
    "affinity_primary",
    "affinity_secondary",
    "affinity_tertiary",
    "competitor_of_previous",
    "similar_talent",
    "bidirectional_walk",
    "audience_demographic",
    "life_stage",
    "exclusivity_adjacent",
    "softener",
    "manual",
]

_PROPOSAL_PRIORITY: dict[str, int] = {
    "affinity_primary": 0,
    "affinity_secondary": 1,
    "affinity_tertiary": 2,
    "competitor_of_previous": 3,
    "similar_talent": 4,
    "bidirectional_walk": 5,
    "audience_demographic": 6,
    "life_stage": 7,
    "exclusivity_adjacent": 8,
    "softener": 9,
    "manual": 10,
}


def proposal_source_priority(source: str) -> int:
    """Lower = higher priority. Used for dedup when an industry surfaces
    via multiple sources; the lowest-priority source's rationale wins."""
    return _PROPOSAL_PRIORITY.get(source, 999)


@dataclass(frozen=True)
class IndustryProposal:
    """One industry proposed for inclusion in Phase 2 brand discovery.

    Each industry that surfaces from any Phase 1 step is wrapped in an
    IndustryProposal carrying the rationale + source. The orchestrator
    dedupes by ``industry_id``, keeping the highest-priority source's
    rationale (see ``proposal_source_priority``).
    """

    industry_id: str
    rationale: str
    source: IndustryProposalSource


@dataclass
class IndustryReviewItem:
    """One entry in the Phase 1.5 industry-review queue.

    The agency operator approves/deselects per item before Phase 2 fires.
    ``alternate_rationales`` lists the other sources that surfaced the
    same industry (for transparency in the UI).
    """

    industry_id: str
    rationale: str
    source: str
    approved: bool = True
    alternate_rationales: list[dict[str, str]] = field(default_factory=list)
