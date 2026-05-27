"""add retrieval_count to memo

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-27 15:00:00.000000

Per the M2 plan: ``memo.schema.json`` includes ``retrieval_count`` (Integer,
default 0). M1's initial migration omitted it. M2 adds it because the
``read_memos`` tool increments it on every retrieval (atomic UPDATE in
``MemoRepository.mark_retrieved``).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic identifiers
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add ``memo.retrieval_count`` column with default 0.

    Uses ``IF NOT EXISTS`` because M1's migration 0002 uses
    ``Base.metadata.create_all()`` which picks up the M2-updated model
    definition + creates the column eagerly. Without IF NOT EXISTS this
    migration fails on fresh-DB CI runs (where 0002 + 0003 apply
    back-to-back against an empty DB). In production, where 0002 has
    already deployed before 0003 lands, IF NOT EXISTS is a no-op safety
    net.
    """
    # Raw SQL to use Postgres's IF NOT EXISTS clause.
    op.execute(
        "ALTER TABLE memo ADD COLUMN IF NOT EXISTS retrieval_count "
        "INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    """Drop the column."""
    op.execute("ALTER TABLE memo DROP COLUMN IF EXISTS retrieval_count")
