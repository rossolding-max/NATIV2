"""``proposal_pack`` table — Phase 4.6 commercial proposal (hard commercial gate)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin
from app.models.sqla._mixins import PackVersioningMixin


class ProposalPack(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin, PackVersioningMixin):
    __tablename__ = "proposal_pack"

    proposal_pack_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    commercial_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("deal_id", "version", name="ux_proposal_pack_deal_version"),
        Index(
            "ix_proposal_pack_latest_per_deal",
            "deal_id",
            unique=True,
            postgresql_where=text("is_latest = true"),
        ),
        Index("ix_proposal_pack_data_gin", "data", postgresql_using="gin"),
    )
