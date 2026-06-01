"""add M8.1 contact outreach_recommendation + revealed_at scalar columns

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-01 12:00:00.000000

M8.1 reshapes contact enrichment into a 3-phase flow: broad capture
(Phase A, no email), classify+recommend (Phase B, in-memory), user-gated
bulk email reveal (Phase C). Two new scalar columns surface the new
state on the existing ``brand_contact`` table:

- ``outreach_recommendation`` (String(32), default 'requires_review'):
  the LLM's per-contact recommendation flag from the extended Step 6
  Haiku call. Values: ``recommended`` / ``not_recommended`` /
  ``requires_review``. Indexed because the operator UI filters the
  broad pool by this.

- ``revealed_at`` (TIMESTAMPTZ, nullable): timestamp Phase C reveal
  fired for this contact. Null until reveal attempted; populated even
  when the reveal returned no verified email (so "we tried, nothing"
  is visible). Partial index on NOT NULL for "show unrevealed" filter.

Uses ``IF NOT EXISTS`` clauses to keep CI's ``create_all()`` flow + the
production migration flow both happy — same pattern as 0003 / 0004 / 0005.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Alembic identifiers
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add M8.1 scalar columns + their indexes."""
    op.execute(
        """
        ALTER TABLE brand_contact
            ADD COLUMN IF NOT EXISTS outreach_recommendation
                VARCHAR(32) NOT NULL DEFAULT 'requires_review',
            ADD COLUMN IF NOT EXISTS revealed_at
                TIMESTAMP WITH TIME ZONE NULL;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_brand_contact_outreach_recommendation "
        "ON brand_contact (outreach_recommendation);"
    )
    # Partial index — most rows are unrevealed (revealed_at IS NULL); the
    # filter the UI actually uses is "show me revealed contacts", so we
    # index only the non-null subset.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_brand_contact_revealed_at "
        "ON brand_contact (revealed_at) WHERE revealed_at IS NOT NULL;"
    )


def downgrade() -> None:
    """Drop the M8.1 columns + their indexes."""
    op.execute("DROP INDEX IF EXISTS ix_brand_contact_revealed_at;")
    op.execute("DROP INDEX IF EXISTS ix_brand_contact_outreach_recommendation;")
    op.execute(
        """
        ALTER TABLE brand_contact
            DROP COLUMN IF EXISTS revealed_at,
            DROP COLUMN IF EXISTS outreach_recommendation;
        """
    )
