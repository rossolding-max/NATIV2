"""``pitch_angle`` table — reusable outreach angle library (Phase 3b).

Seed data (42 angles in ``data/pitch_angles.json``) populates in M9
(outreach milestone owns it). M1 only creates the empty table.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin


class PitchAngle(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin):
    __tablename__ = "pitch_angle"

    angle_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    authored_strength_score: Mapped[float] = mapped_column(
        Numeric(precision=4, scale=3), nullable=False, default=0.5
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_pitch_angle_data_gin", "data", postgresql_using="gin"),)
