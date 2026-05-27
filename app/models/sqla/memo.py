"""``memo`` table — agent learning memos (M2+ memo store).

Per the M1 plan: ``is_active`` is a **computed property**, not a column.
Definition: ``not is_deleted AND (expires_at IS NULL OR expires_at > now())``.

Implemented as a SQLAlchemy ``hybrid_property`` so it works in both Python
and SQL queries.

Content stays plaintext (M2 agents read via tag-filter SQL — encryption
would force per-read decryption on a hot path).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, and_, or_, sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin


class Memo(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin):
    __tablename__ = "memo"

    memo_id: Mapped[str] = mapped_column(String(32), primary_key=True)

    memo_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    content_markdown: Mapped[str] = mapped_column(String, nullable=False)

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retrieval_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    # tags as JSONB: { talent_ids[], brand_ids[], industry_ids[], deal_ids[],
    # topics[], phase_context }. Queried via GIN.
    tags: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    @hybrid_property
    def is_active(self) -> bool:  # type: ignore[override]
        """Pythonic accessor: alive if not soft-deleted + not expired."""
        if self.is_deleted:
            return False
        if self.expires_at is None:
            return True
        return self.expires_at > datetime.now(UTC)

    @is_active.expression  # type: ignore[no-untyped-call]
    def is_active(cls):  # noqa: N805 — hybrid_property class-method idiom
        """SQL-side expression for use in ``where()`` clauses."""
        return and_(
            cls.is_deleted.is_(False),  # type: ignore[attr-defined]
            or_(cls.expires_at.is_(None), cls.expires_at > sql.func.now()),  # type: ignore[attr-defined]
        )

    __table_args__ = (Index("ix_memo_tags_gin", "tags", postgresql_using="gin"),)
