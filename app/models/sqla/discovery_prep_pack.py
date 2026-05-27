"""``discovery_prep_pack`` table — Phase 4.5 AI prep pack."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin
from app.models.sqla._mixins import PackVersioningMixin


class DiscoveryPrepPack(
    Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin, PackVersioningMixin
):
    __tablename__ = "discovery_prep_pack"

    prep_pack_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("deal_id", "version", name="ux_prep_pack_deal_version"),
        Index(
            "ix_prep_pack_latest_per_deal",
            "deal_id",
            unique=True,
            postgresql_where=text("is_latest = true"),
        ),
        Index("ix_prep_pack_data_gin", "data", postgresql_using="gin"),
    )
