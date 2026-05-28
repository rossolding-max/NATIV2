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


@dataclass
class QualifiedCandidate:
    """A merged + scored + qualified candidate ready to write to DB."""

    brand_id: str
    brand_name: str
    industry_id: str
    score: float
    tier: Literal["re-engage", "primary", "secondary", "tertiary"]
    sources: list[CandidateSource]
    qualification_score: float
    qualification_tier: Literal["qualified", "speculative", "unqualified"]
    qualification_signals: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blocked: bool = False
    block_reason: str | None = None


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
