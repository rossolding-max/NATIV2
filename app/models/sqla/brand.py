"""``brand`` table — global reference catalogue.

**Single global-table carve-out** per the M1 plan: brands are shared across
agencies (v2 will revisit). Does NOT inherit ``AgencyScopedMixin`` — there
is no ``agency_id`` column on this table.

PK = ``brand_id`` (kebab-case slug derived from ``name``).

The 290 brand records from ``data/brand_industry_map.json`` populate this
table via ``scripts/import_brand_industry_map.py`` (M1 PR 3).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, SoftDeleteMixin, TimestampedMixin


class Brand(Base, SoftDeleteMixin, TimestampedMixin):
    """Global brand reference. Shared across agencies (no ``agency_id``)."""

    __tablename__ = "brand"

    # ── Identity ──────────────────────────────────────────────────────
    brand_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """Slug derived from `name`. Format: `^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$`."""

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    """Display name. Source of `brand_id` slugification."""

    # ── Cross-phase reference ─────────────────────────────────────────
    # industry_id resolves against the in-memory taxonomy loaded via
    # ``app.utils.taxonomies`` (per M1 plan: reference data stays in-memory).
    # Pydantic + the import script validate against the taxonomy; no DB FK.
    industry_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # ── Queryable scalar fields ───────────────────────────────────────
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hq_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    company_stage: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    typical_campaign_tier: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    # ── Nested object payload ─────────────────────────────────────────
    # Holds: aliases, sells_in_countries, creator_program_presence, revenue,
    # headcount, social_followers, social_handles, legal_entity. All these
    # arrive whole-record from `brand_industry_map.json`; downstream phases
    # mutate sub-fields (e.g. M9 discovery accretes social_handles).
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        CheckConstraint(
            "brand_id ~ '^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$'",
            name="ck_brand_id_format",
        ),
        Index("ix_brand_data_gin", "data", postgresql_using="gin"),
    )
