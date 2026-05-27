"""``agency_profile`` table — v0.1 single-agency record.

The lifespan singleton loads the agency_id from this table at startup
(per ``docs/auth_and_authorization.md``).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import UUID as SA_UUID
from sqlalchemy import Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampedMixin


class AgencyProfile(Base, SoftDeleteMixin, TimestampedMixin):
    """Per-agency identity + setup + branding + invoice template."""

    __tablename__ = "agency_profile"

    # PK is the agency_id (UUID) — agency_profile is the ROOT, not scoped by it.
    agency_id: Mapped[UUID] = mapped_column(SA_UUID(as_uuid=True), primary_key=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="setup_in_progress", index=True
    )

    # Phase 0 setup state: agents, sending_mailboxes, branding, invoice_template,
    # billing_entity, default_signature_template, default_commission_rate,
    # default_commission_model, etc.
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (Index("ix_agency_profile_data_gin", "data", postgresql_using="gin"),)
