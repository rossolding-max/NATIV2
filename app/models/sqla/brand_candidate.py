"""``brand_candidate`` table — per-(talent, brand) discovery result (Phase 2)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin


class BrandCandidate(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin):
    __tablename__ = "brand_candidate"

    candidate_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    talent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("talent.talent_id"), nullable=False, index=True
    )
    brand_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("brand.brand_id"), nullable=False, index=True
    )
    tier: Mapped[str] = mapped_column(String(16), nullable=False, default="qualified", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="new", index=True)
    score: Mapped[float | None] = mapped_column(Numeric(precision=4, scale=3), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_brand_candidate_data_gin", "data", postgresql_using="gin"),
        Index("ix_brand_candidate_talent_brand", "talent_id", "brand_id", unique=True),
    )
