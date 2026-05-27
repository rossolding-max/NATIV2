"""``talent_vault`` table — encrypted OAuth tokens per (talent, platform).

Per the M5 plan: tokens are stored in a SEPARATE table from ``talent.data``
JSONB so that column-level pgcrypto via ``EncryptedString`` applies cleanly.
The ``talent.platforms[].api_credentials.access_token_ref`` field in the
JSONB column carries a REFERENCE string (e.g. ``vault:talent_<id>:meta``)
that points at the vault row.

Composite PK ``(talent_id, platform)`` — one row per platform connection.

Soft-delete + timestamps come via the mixins; ``agency_id`` is included for
multi-tenant scoping but optional in v0.1 (single-tenant).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as SA_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampedMixin
from app.utils.encryption import EncryptedString


class TalentVault(Base, SoftDeleteMixin, TimestampedMixin):
    """Encrypted OAuth credentials for one (talent, platform) pair."""

    __tablename__ = "talent_vault"

    talent_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("talent.talent_id", ondelete="CASCADE"),
        primary_key=True,
    )
    platform: Mapped[str] = mapped_column(String(32), primary_key=True)
    # Optional multi-tenant scope (mirrors talent.agency_id; not enforced as FK).
    agency_id: Mapped[UUID | None] = mapped_column(SA_UUID(as_uuid=True), nullable=True)

    access_token: Mapped[str] = mapped_column(EncryptedString(), nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    scope_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_talent_vault_agency", "agency_id"),
        Index("ix_talent_vault_platform", "platform"),
    )
