"""``industry_review`` — Phase 1.5 human-in-the-loop review queue (M7.7).

When an agency operator triggers a ``full_build`` discovery run, Phase 1
compiles a comprehensive industry universe and persists it here as a
``pending`` record. The operator reviews, adds/deselects industries,
then approves. Approval enqueues the Phase 2 brand-universe-build
Celery task.

One pending record per (talent, agency) at a time. Approving a record
makes it immutable; a subsequent ``full_build`` trigger creates a new
record.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin


class IndustryReview(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin):
    __tablename__ = "industry_review"

    review_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    talent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("talent.talent_id"), nullable=False, index=True
    )
    # "pending" | "approved" | "rejected"
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    # JSONB list of IndustryReviewItem dicts:
    #   [{"industry_id": str, "rationale": str, "source": str,
    #     "approved": bool, "alternate_rationales": [{source, rationale}, ...]}]
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # Optional search_run_id pointing back at the run that produced this review.
    search_run_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_industry_review_data_gin", "items", postgresql_using="gin"),
        Index("ix_industry_review_talent_status", "talent_id", "status"),
    )
