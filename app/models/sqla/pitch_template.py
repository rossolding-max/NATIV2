"""``pitch_template`` table — reusable outreach sequence templates (Phase 3b)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin


class PitchTemplate(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin):
    __tablename__ = "pitch_template"

    template_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    target_decision_role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_pitch_template_data_gin", "data", postgresql_using="gin"),)
