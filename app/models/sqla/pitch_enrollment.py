"""``pitch_enrollment`` table — active outreach sequence per contact (Phase 3b)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin


class PitchEnrollment(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin):
    __tablename__ = "pitch_enrollment"

    enrollment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    talent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("talent.talent_id"), nullable=False, index=True
    )
    brand_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("brand.brand_id"), nullable=False, index=True
    )
    contact_id: Mapped[str] = mapped_column(
        String(96), ForeignKey("brand_contact.contact_id"), nullable=False, index=True
    )
    template_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="drafted", index=True)
    created_deal_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    killed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_pitch_enrollment_data_gin", "data", postgresql_using="gin"),)
