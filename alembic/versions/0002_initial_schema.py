"""M1 initial schema — 16 domain tables + pgcrypto extension.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-27 14:30:00.000000

Single bootstrap migration. Subsequent migrations (M2+) use granular
``op.add_column``, ``op.create_table`` etc. for individual changes.

The migration uses ``Base.metadata.create_all()`` because all 16 tables
land together in M1 and the SQLA model definitions are the canonical
source of truth. The downside is offline mode (``alembic upgrade head
--sql``) is not supported for this revision — fine in M1, since offline
SQL dumps aren't a requirement yet.

Tables created (FK-safe creation order is handled by metadata.create_all
internally):

- agency_profile, brand (no FK in)
- talent (agency-scoped)
- brand_candidate, brand_contact, brand_deal (FK: talent, brand)
- pitch_template, pitch_angle (agency-scoped, no other FK)
- pitch_enrollment (FK: talent, brand, brand_contact)
- deal (FK: talent, brand, brand_contact)
- discovery_prep_pack, proposal_pack, contract_pack, invoice_pack,
  performance_report_pack (FK: deal)
- memo (no FK; tags are JSONB)
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.db.base import Base
from app.models.sqla import *  # noqa: F401, F403 — import side-effect populates Base.metadata

# Alembic identifiers
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create pgcrypto extension + all 16 domain tables."""
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    """Drop all 16 domain tables (pgcrypto extension stays)."""
    Base.metadata.drop_all(op.get_bind())
