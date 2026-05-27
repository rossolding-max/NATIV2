"""empty baseline

Revision ID: 0001
Revises:
Create Date: 2026-05-27 14:00:00.000000

M0 baseline. Establishes the alembic_version table so M1's first real
migration has somewhere to chain off. No schema changes here.
"""

from __future__ import annotations

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """No-op baseline. Real tables land in M1."""


def downgrade() -> None:
    """No-op downgrade."""
