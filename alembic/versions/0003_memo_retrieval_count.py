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
    """Add ``memo.retrieval_count`` column with default 0."""
    op.add_column(
        "memo",
        sa.Column(
            "retrieval_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    """Drop the column."""
    op.drop_column("memo", "retrieval_count")
