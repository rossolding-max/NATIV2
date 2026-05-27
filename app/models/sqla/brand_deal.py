"""``brand_deal`` table — per-talent historical deals (Phase 1.5)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin


class BrandDeal(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin):
    __tablename__ = "brand_deal"

    brand_deal_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    talent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("talent.talent_id"), nullable=False, index=True
    )
    brand_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("brand.brand_id"), nullable=False, index=True
    )

    fee_usd: Mapped[float | None] = mapped_column(Numeric(precision=12, scale=2), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)

    started_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    ended_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_brand_deal_data_gin", "data", postgresql_using="gin"),)
