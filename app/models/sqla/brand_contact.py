"""``brand_contact`` table — per-brand named contacts (Phase 3a).

Top-level scalars: contact_id, brand_id, name, decision_role,
outreach_recommendation (M8.1), email (encrypted), revealed_at (M8.1),
do_not_contact. Nested enrichment + qualification + pitch_history
plus rationales (decision_role_rationale, outreach_recommendation_rationale)
in ``data`` JSONB.

Email is a top-level encrypted column because reply classifier + DNC
enforcement queries need it.

M8.1 scalar columns:
- ``outreach_recommendation`` — mirrors ``decision_role`` so the UI can
  filter the broad capture pool by the LLM's "should you pitch this
  contact" recommendation.
- ``revealed_at`` — timestamp the operator triggered an Apollo
  ``/people/match`` email-reveal call. Null until reveal attempted;
  populated even on reveal failure so "we tried, no verified email"
  is visible.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin
from app.utils.encryption import EncryptedString


class BrandContact(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin):
    __tablename__ = "brand_contact"

    contact_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    brand_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("brand.brand_id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    decision_role: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", index=True
    )
    # M8.1 — LLM's "should the operator pitch this contact directly"
    # classification. Drives the UI badge so the operator can filter the
    # broad Phase A capture pool to actual outreach candidates.
    outreach_recommendation: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="requires_review",
        server_default="requires_review",
        index=True,
    )
    email: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    # M8.1 — set when an operator-triggered Apollo /people/match call
    # has been attempted for this contact. Null = email never revealed
    # (Phase A state); non-null = reveal attempted (even if no verified
    # email came back). Indexed because the UI surfaces "show only
    # unrevealed" inventories.
    revealed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    do_not_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True, server_default="false"
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_brand_contact_data_gin", "data", postgresql_using="gin"),)
