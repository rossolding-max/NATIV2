"""``deal`` table — Phase 4 lifecycle deal.

The most complex domain entity: 6 stages by 28 substages, nested packs,
discovery_debrief extraction, negotiation_log, amendment_log,
posting_schedule, interim_kpi_snapshots, etc. All nested fields live in
JSONB columns; top-level surfaces are PK, FK chain, stage/substage, money
totals, and key timestamps for cron queries.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import AgencyScopedMixin, Base, SoftDeleteMixin, TimestampedMixin


class Deal(Base, AgencyScopedMixin, SoftDeleteMixin, TimestampedMixin):
    __tablename__ = "deal"

    deal_id: Mapped[str] = mapped_column(String(80), primary_key=True)

    # FK chain
    talent_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("talent.talent_id"), nullable=False, index=True
    )
    brand_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("brand.brand_id"), nullable=False, index=True
    )
    primary_contact_id: Mapped[str | None] = mapped_column(
        String(96), ForeignKey("brand_contact.contact_id"), nullable=True
    )
    originating_enrollment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # State machine
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="lead", index=True)
    substage: Mapped[str] = mapped_column(
        String(64), nullable=False, default="new_lead", index=True
    )
    is_terminal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True, server_default="false"
    )
    is_won: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Money + scheduling
    expected_value_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )
    actual_final_value_usd: Mapped[float | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )
    expected_close_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_action_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Pointer to latest pack of each type (denormalised from pack tables)
    latest_prep_pack_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latest_proposal_pack_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latest_contract_pack_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    latest_performance_report_pack_id: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Everything else nested: lead.*, proposal.*, contract.*, delivery.*,
    # close.*, stage_history[], attachments[], notes[].
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_deal_data_gin", "data", postgresql_using="gin"),
        Index("ix_deal_stage_substage", "stage", "substage"),
    )
