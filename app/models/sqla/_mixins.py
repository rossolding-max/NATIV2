"""Shared mixins specific to M1 SQLA models.

The cross-cutting mixins (``AgencyScopedMixin``, ``SoftDeleteMixin``,
``TimestampedMixin``) live in ``app.db.base`` and are inherited by every
domain model. This module adds **M1-specific** mixins layered on top:

- ``PackVersioningMixin`` — used by the 5 pack tables
  (discovery_prep_pack, proposal_pack, contract_pack, invoice_pack,
  performance_report_pack). Each pack has ``version`` + ``parent_version``
  + ``is_latest`` + unique constraint on (deal_id, version).
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column


class PackVersioningMixin:
    """Versioning columns shared by every pack table.

    Pack tables also need a partial unique index on
    ``(deal_id) WHERE is_latest = true`` — declared in each pack's
    ``__table_args__`` because partial indexes vary by table name.
    """

    deal_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("deal.deal_id"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_latest: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True, server_default="false"
    )
