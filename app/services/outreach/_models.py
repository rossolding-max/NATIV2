"""Lightweight dataclasses passed between outreach pipeline steps.

Mirrors ``discovery/_models.py`` + ``contact_enrichment/_models.py``:
dataclasses for in-flight state; Pydantic codegen
(``pitch_enrollment_schema.py``, ``deal_schema.py``) only used at the
persistence / API boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class StepGeneration:
    """One generated step in a pitch sequence (mid-pipeline)."""

    step_number: int
    intent: str
    subject: str
    body: str
    angles_used: dict[str, str | None] = field(default_factory=dict)
    personalization_fields_used: list[str] = field(default_factory=list)
    reasoning: str = ""
    model_used: str = ""
    timing_offset_days: int = 0
    validation_warnings: list[str] = field(default_factory=list)


@dataclass
class EnrollmentDraft:
    """A generated enrollment awaiting persistence + approval."""

    enrollment_id: str
    talent_id: str
    contact_id: str
    brand_id: str
    template_id: str
    steps: list[StepGeneration] = field(default_factory=list)
    sources_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class EnrollmentRunResult:
    """The output of one ``generate_enrollment`` call."""

    talent_id: str
    contact_id: str
    brand_id: str
    run_id: str
    generated_at: datetime
    draft: EnrollmentDraft | None = None
    block_reason: str | None = None  # populated when policy filter blocks
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
