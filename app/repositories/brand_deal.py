"""``BrandDealRepository`` — CRUD + JSONB patch + outcome filter for brand_deal.

M6 adds the query helpers (``find_by_talent``, ``find_by_outcome``) and the
JSONB patch path (``patch_deal_data``) on top of ``BaseRepository``.

``brand_deal.outcome`` is stored both as the indexed scalar column AND
inside the JSONB ``data`` blob. ``set_outcome_column`` writes to the
column for fast filtering; the service layer keeps the JSONB shadow in
sync via ``patch_deal_data``.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import NotFoundError
from app.models.sqla.brand_deal import BrandDeal
from app.repositories.base import BaseRepository


def _deep_merge(base: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    """Same semantics as ``TalentRepository._deep_merge``: lists REPLACE, dicts merge."""
    result = deepcopy(base)
    for key, value in diff.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class BrandDealRepository(BaseRepository[BrandDeal]):
    """CRUD + JSONB patch on the ``brand_deal`` table."""

    model = BrandDeal
    pk_attr = "brand_deal_id"

    def __init__(self, session: AsyncSession, agency_id: UUID | None = None) -> None:
        super().__init__(session, agency_id or UUID(int=0))

    # ── Lookups ──────────────────────────────────────────────────────

    async def find_by_talent(
        self, talent_id: str, *, include_deleted: bool = False, limit: int = 200
    ) -> list[BrandDeal]:
        """All deals for a talent (newest first by ``last_updated_at``, then by id)."""
        stmt = (
            select(BrandDeal)
            .where(
                self._base_filter(include_deleted=include_deleted), BrandDeal.talent_id == talent_id
            )
            .order_by(BrandDeal.last_updated_at.desc().nulls_last(), BrandDeal.brand_deal_id)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_outcome(
        self, talent_id: str, outcome: str, *, include_deleted: bool = False
    ) -> list[BrandDeal]:
        """Per-talent filter on the indexed outcome column."""
        stmt = (
            select(BrandDeal)
            .where(
                self._base_filter(include_deleted=include_deleted),
                BrandDeal.talent_id == talent_id,
                BrandDeal.outcome == outcome,
            )
            .order_by(BrandDeal.last_updated_at.desc().nulls_last(), BrandDeal.brand_deal_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Mutations ────────────────────────────────────────────────────

    async def patch_deal_data(self, deal_id: str, diff: dict[str, Any]) -> BrandDeal:
        """Deep-merge ``diff`` into the JSONB ``data`` column + bump ``last_updated_at``."""
        instance = await self.get_by_id(deal_id)
        if instance is None:
            raise NotFoundError(
                f"brand_deal {deal_id!r} not found", detail={"brand_deal_id": deal_id}
            )
        merged = _deep_merge(dict(instance.data or {}), diff)
        instance.data = merged
        instance.last_updated_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def set_outcome_column(self, deal_id: str, outcome: str) -> BrandDeal:
        """Write the indexed scalar ``outcome`` column + bump ``last_updated_at``."""
        stmt = (
            update(BrandDeal)
            .where(self._base_filter(), BrandDeal.brand_deal_id == deal_id)
            .values(outcome=outcome, last_updated_at=datetime.now(UTC))
            .returning(BrandDeal)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(
                f"brand_deal {deal_id!r} not found", detail={"brand_deal_id": deal_id}
            )
        await self._session.flush()
        return row
