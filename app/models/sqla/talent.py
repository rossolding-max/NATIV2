"""``talent`` table — per-talent profile.

Top-level surface: identity + status + key timestamps. Everything nested
(platforms, rate_card, contact, billing_entity, contract_template,
brand_preferences, working_terms, press_kit, audience_demographics) goes
in the ``data`` JSONB column.

PII fields (talent.contact.email, billing_entity.legal_name) sit inside
``data`` and are NOT individually encrypted at M1 (the surrounding column
is plaintext JSONB). Phase 5 onboarding may surface them as separate
EncryptedString columns when search becomes a query requirement; tracked
as a v0.2 follow-up.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin


class Talent(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin):
    __tablename__ = "talent"

    talent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="onboarding", index=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "talent_id ~ '^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$'",
            name="ck_talent_id_format",
        ),
        Index("ix_talent_agency", "agency_id", "talent_id"),
        Index("ix_talent_data_gin", "data", postgresql_using="gin"),
    )
