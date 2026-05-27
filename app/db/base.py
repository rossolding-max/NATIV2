"""SQLAlchemy declarative base + shared mixins. See ``docs/code_conventions.md`` § 6.

All domain tables inherit ``Base`` + the three shared mixins:

- ``AgencyScopedMixin`` — multi-tenant readiness (every row carries ``agency_id``).
- ``SoftDeleteMixin`` — system-wide soft-delete (``is_deleted`` + audit fields).
- ``TimestampedMixin`` — ``created_at`` / ``updated_at`` UTC tz-aware datetimes.

M0 only defines the surface; real models populate the metadata in M1.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import UUID as SA_UUID
from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Application-wide declarative base. M1's hand-written SQLA models inherit
    this class.
    """


def _utcnow() -> datetime:
    """Return current UTC time with tzinfo (per CLAUDE.md UTC discipline)."""
    return datetime.now(UTC)


class AgencyScopedMixin:
    """Multi-tenant readiness — every domain row carries ``agency_id``.

    Repository-layer filtering enforces ``agency_id = current_agency_id``
    on every read in v0.1. v2 layers Postgres row-level security on top.
    See ``docs/auth_and_authorization.md``.
    """

    agency_id: Mapped[uuid.UUID] = mapped_column(SA_UUID(as_uuid=True), nullable=False, index=True)


class SoftDeleteMixin:
    """System-wide soft-delete columns.

    Repositories MUST filter ``is_deleted == False`` by default; pass
    ``include_deleted=True`` to opt in to historical rows.
    """

    is_deleted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True, server_default="false"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by_agent_id: Mapped[str | None] = mapped_column(String, nullable=True)


class TimestampedMixin:
    """``created_at`` + ``updated_at`` in UTC. Set in Python (no Postgres NOW())
    so tests get deterministic values via freezing.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
