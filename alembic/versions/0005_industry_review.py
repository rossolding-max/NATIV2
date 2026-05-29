"""add industry_review for the M7.7 Phase 1.5 human-in-the-loop queue

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-29 21:00:00.000000

Persists each Phase 1 industry-compilation output so the agency operator
can review/edit before triggering the (expensive) Phase 2 brand universe
build. One pending record per (talent, agency) at a time.

Uses ``CREATE TABLE IF NOT EXISTS`` to keep CI's create_all() flow + the
production migration flow both clean — same pattern as 0003 / 0004.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Alembic identifiers
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``industry_review`` table."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS industry_review (
            review_id VARCHAR(80) NOT NULL PRIMARY KEY,
            talent_id VARCHAR(64) NOT NULL
                REFERENCES talent(talent_id) ON DELETE CASCADE,
            agency_id UUID NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            items JSONB NOT NULL DEFAULT '[]'::jsonb,
            search_run_id VARCHAR(80) NULL,
            approved_at TIMESTAMP WITH TIME ZONE NULL,

            -- TimestampedMixin
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            -- SoftDeleteMixin
            is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at TIMESTAMP WITH TIME ZONE NULL,
            deleted_by_agent_id VARCHAR(64) NULL
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_industry_review_talent "
        "ON industry_review (talent_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_industry_review_status "
        "ON industry_review (status);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_industry_review_talent_status "
        "ON industry_review (talent_id, status);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_industry_review_data_gin "
        "ON industry_review USING GIN (items);"
    )


def downgrade() -> None:
    """Drop ``industry_review``."""
    op.execute("DROP TABLE IF EXISTS industry_review CASCADE")
