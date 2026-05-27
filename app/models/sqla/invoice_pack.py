"""``invoice_pack`` table — Phase 4.8 invoice pack.

``composed_markdown`` carries the full invoice text and is encrypted at
rest via ``EncryptedString``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin
from app.models.sqla._mixins import PackVersioningMixin
from app.utils.encryption import EncryptedString


class InvoicePack(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin, PackVersioningMixin):
    __tablename__ = "invoice_pack"

    invoice_pack_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    invoice_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    total_usd: Mapped[float | None] = mapped_column(Numeric(precision=12, scale=2), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    payment_received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    composed_markdown: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("deal_id", "version", name="ux_invoice_pack_deal_version"),
        Index(
            "ix_invoice_pack_latest_per_deal",
            "deal_id",
            unique=True,
            postgresql_where=text("is_latest = true"),
        ),
        Index("ix_invoice_pack_data_gin", "data", postgresql_using="gin"),
    )
