"""``PitchAngleRepository`` — Phase 3b angle library lookups.

The 42-angle library seeded by ``scripts/seed_pitch_angles.py``. M9's
``angle_filter`` reads from here to pick candidates per step.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sqla.pitch_angle import PitchAngle
from app.repositories.base import BaseRepository


class PitchAngleRepository(BaseRepository[PitchAngle]):
    """CRUD + category finder + full-list reader."""

    model = PitchAngle
    pk_attr = "angle_id"

    def __init__(self, session: AsyncSession, agency_id: UUID | None = None) -> None:
        super().__init__(session, agency_id or UUID(int=0))

    async def find_all(self) -> list[PitchAngle]:
        stmt = (
            select(PitchAngle)
            .where(self._base_filter())
            .order_by(PitchAngle.authored_strength_score.desc().nulls_last())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_category(self, category: str) -> list[PitchAngle]:
        stmt = (
            select(PitchAngle)
            .where(self._base_filter(), PitchAngle.category == category)
            .order_by(PitchAngle.authored_strength_score.desc().nulls_last())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
