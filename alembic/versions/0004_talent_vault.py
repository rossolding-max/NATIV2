"""add talent_vault for encrypted OAuth tokens

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-27 21:00:00.000000

Per the M5 plan: per-(talent, platform) OAuth tokens stored encrypted via
the ``EncryptedString`` TypeDecorator (column-level pgcrypto). Separate
table so the JSONB blob on ``talent`` doesn't need to mix pgp_sym_encrypt
calls inline.

Uses ``CREATE TABLE IF NOT EXISTS`` because the M1 migration 0002 calls
``Base.metadata.create_all()`` which picks up the M5-added TalentVault
model + creates the table eagerly. Without IF NOT EXISTS this migration
fails on fresh-DB CI runs (where 0002 + 0004 apply back-to-back against
an empty DB). In production, where 0002 already deployed before 0004
lands, IF NOT EXISTS is a no-op safety net. Same pattern as 0003.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# Alembic identifiers
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create ``talent_vault`` table with column-level pgcrypto on tokens."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS talent_vault (
            talent_id VARCHAR(64) NOT NULL
                REFERENCES talent(talent_id) ON DELETE CASCADE,
            platform VARCHAR(32) NOT NULL,
            agency_id UUID NULL,

            access_token BYTEA NOT NULL,
            refresh_token BYTEA NULL,

            expires_at TIMESTAMP WITH TIME ZONE NULL,
            scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
            scope_validated_at TIMESTAMP WITH TIME ZONE NULL,

            -- TimestampedMixin
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            -- SoftDeleteMixin
            is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at TIMESTAMP WITH TIME ZONE NULL,
            deleted_by_agent_id VARCHAR(64) NULL,

            PRIMARY KEY (talent_id, platform)
        );
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_talent_vault_agency ON talent_vault (agency_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_talent_vault_platform ON talent_vault (platform);")


def downgrade() -> None:
    """Drop ``talent_vault``."""
    op.execute("DROP TABLE IF EXISTS talent_vault CASCADE")
