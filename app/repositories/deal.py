"""``DealRepository`` — Phase 4 deal lifecycle + Phase-3b → Phase-4 handoff.

M9 owns the GAP-06 bidirectional-FK INSERT that fires when an outreach
reply classifies as ``interested``. M10 will own the full state-machine
transitions; for now we only support the lead-stage INSERT path.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sqla.deal import Deal
from app.repositories.base import BaseRepository


class DealRepository(BaseRepository[Deal]):
    """CRUD + lead-stage insertion driven by M9 outreach replies."""

    model = Deal
    pk_attr = "deal_id"

    def __init__(self, session: AsyncSession, agency_id: UUID | None = None) -> None:
        super().__init__(session, agency_id or UUID(int=0))

    async def find_by_enrollment(self, enrollment_id: str) -> Deal | None:
        """Return the deal originating from this enrollment (or None)."""
        stmt = select(Deal).where(
            self._base_filter(),
            Deal.originating_enrollment_id == enrollment_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def insert_lead_from_enrollment(
        self,
        *,
        enrollment_id: str,
        talent_id: str,
        brand_id: str,
        contact_id: str,
        decision_role_at_pitch: str,
        substage: str = "new_lead",
        extra_data: dict[str, Any] | None = None,
        agency_id: UUID | None = None,
    ) -> Deal:
        """Create a Phase-4 lead deal originated by an outreach reply.

        The companion bidirectional UPDATE on
        ``pitch_enrollment.created_deal_id`` is the caller's job — both
        ops must run inside one SQLA transaction (no intermediate commit)
        per the GAP-06 audit gate.
        """
        bound = agency_id or self._agency_id
        deal_id = f"deal_{uuid4().hex[:24]}"
        data: dict[str, Any] = {
            "originating_enrollment_id": enrollment_id,
            "originating_decision_role_at_pitch": decision_role_at_pitch,
        }
        if extra_data:
            data.update(extra_data)
        instance = Deal(
            deal_id=deal_id,
            talent_id=talent_id,
            brand_id=brand_id,
            primary_contact_id=contact_id,
            originating_enrollment_id=enrollment_id,
            stage="lead",
            substage=substage,
            data=data,
        )
        instance.agency_id = bound
        await self.create(instance)
        return instance
