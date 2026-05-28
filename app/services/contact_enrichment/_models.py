"""Lightweight dataclasses passed between pipeline steps.

Mirrors the ``discovery/_models.py`` pattern: dataclasses for in-flight
records, with the Pydantic codegen (``brand_contact_schema.py``) only
used at the persistence / API boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EnrichedContact:
    """A single contact mid-pipeline (after Step 2/3/4, before qualification)."""

    contact_id: str
    brand_id: str
    name: str
    title: str | None = None
    seniority: str | None = None
    function: str | None = None
    linkedin_url: str | None = None
    email_address: str | None = None
    email_verification_status: str | None = None  # verified / catchall / unverified / etc.
    location: dict[str, Any] | None = None
    # Per-step provenance — which vendor surfaced + raw payload for audit.
    sources: list[dict[str, Any]] = field(default_factory=list)
    # decision_role and rationale land after Step 6.
    decision_role: str = "unknown"
    decision_role_rationale: str = ""

    def add_source(self, *, step: str, vendor: str, payload: dict[str, Any]) -> None:
        self.sources.append({"step": step, "vendor": vendor, "payload": payload})


@dataclass
class QualifiedContact:
    """An ``EnrichedContact`` with a qualification score + tier attached."""

    contact: EnrichedContact
    qualification_score: float
    qualification_tier: str  # qualified / speculative / unqualified
    qualification_signals: list[dict[str, Any]]


@dataclass
class EnrichmentRunResult:
    """The full output of one enrichment run for a brand."""

    brand_id: str
    run_id: str
    generated_at: datetime
    contacts: list[QualifiedContact]
    blocked: list[QualifiedContact]
    errors: list[str]
    steps_run: list[str] = field(default_factory=list)
    talent_id: str | None = None  # set when triggered in talent-scoped mode
