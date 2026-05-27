"""``TalentRepository`` — talent profile CRUD + JSONB-patch operations.

Mirrors the ``AgencyProfileRepository`` patch_data + set_status pattern
from M4. Each talent row is agency-scoped via the ``agency_id`` column
on the SQLA model; the base class enforces the filter automatically.

Status state machine (per ``docs/onboarding_workflow.md`` § State machine):
- ``onboarding`` (initial, set by ``Talent`` model default)
- ``active`` (after final validation passes via ``/activate``)
- ``archived`` (user archives)

The legacy term "draft" in the workflow doc maps onto our SQL "onboarding"
default — same lifecycle, just the column name reads "onboarding".
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import NotFoundError
from app.models.sqla.talent import Talent
from app.repositories.base import BaseRepository


def _deep_merge(base: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``diff`` into ``base``. Lists are REPLACED, not concatenated.

    Matches the JSON-Schema patch semantics for ``platforms``, ``previous_brands``,
    ``similar_talent`` — those array fields ARE the values, not collections to
    append to.
    """
    result = deepcopy(base)
    for key, value in diff.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class TalentRepository(BaseRepository[Talent]):
    """CRUD + JSONB patch on the ``talent`` table."""

    model = Talent
    pk_attr = "talent_id"

    def __init__(self, session: AsyncSession, agency_id: UUID | None = None) -> None:
        """Agency scope is optional in v0.1 (single-tenant deploys may have
        ``agency_id`` NULL on talent rows). Pass a zero UUID sentinel when
        unbound; the base filter compares ``agency_id == self._agency_id``
        which produces ``IS NULL`` when ``agency_id`` is None on the row.
        """
        super().__init__(session, agency_id or UUID(int=0))

    # ── Lookups ─────────────────────────────────────────────────────────

    async def get_by_talent_id(
        self, talent_id: str, *, include_deleted: bool = False
    ) -> Talent | None:
        """Convenience alias for ``get_by_id`` with the string PK."""
        return await self.get_by_id(talent_id, include_deleted=include_deleted)

    async def list_by_status(
        self, status: str, *, limit: int = 50, offset: int = 0
    ) -> list[Talent]:
        """List rows matching a status enum for the bound agency."""
        stmt = (
            select(Talent)
            .where(self._base_filter(), Talent.status == status)
            .order_by(Talent.talent_id)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Mutations ──────────────────────────────────────────────────────

    async def patch_data(self, talent_id: str, diff: dict[str, Any]) -> Talent:
        """Deep-merge ``diff`` into the JSONB ``data`` column.

        Read-modify-write inside the caller's transaction. Per the M4
        lesson: the merged result is NOT auto-validated against the JSON
        Schema here — Phase 1 builds the talent incrementally and
        intermediate states will often fail the full schema.
        ``TalentOnboardingService.activate()`` validates at the
        final-step gate instead.
        """
        instance = await self.get_by_id(talent_id)
        if instance is None:
            raise NotFoundError(
                f"talent {talent_id!r} not found",
                detail={"talent_id": talent_id},
            )
        merged = _deep_merge(dict(instance.data or {}), diff)
        instance.data = merged
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def set_status(self, talent_id: str, status: str) -> Talent:
        """Update the ``status`` enum. Caller validates transitions."""
        stmt = (
            update(Talent)
            .where(self._base_filter(), Talent.talent_id == talent_id)
            .values(status=status)
            .returning(Talent)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(
                f"talent {talent_id!r} not found",
                detail={"talent_id": talent_id},
            )
        await self._session.flush()
        return row
