"""``brand_contact`` table — per-brand named contacts (Phase 3a).

Top-level: contact_id, brand_id, name, decision_role, email (encrypted),
do_not_contact flag. Nested enrichment + qualification + pitch_history
in ``data`` JSONB.

Email is a top-level encrypted column because reply classifier + DNC
enforcement queries need it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String
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
    email: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    do_not_contact: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True, server_default="false"
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_brand_contact_data_gin", "data", postgresql_using="gin"),)
