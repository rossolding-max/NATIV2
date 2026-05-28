"""``PitchTemplateRepository`` — Phase 3b template lookups.

Templates are agency-scoped reference data seeded by
``scripts/seed_pitch_templates.py``. M9 reads them; agents can author
custom templates per agency in a later milestone.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sqla.pitch_template import PitchTemplate
from app.repositories.base import BaseRepository


class PitchTemplateRepository(BaseRepository[PitchTemplate]):
    """CRUD + decision-role finder."""

    model = PitchTemplate
    pk_attr = "template_id"

    def __init__(self, session: AsyncSession, agency_id: UUID | None = None) -> None:
        super().__init__(session, agency_id or UUID(int=0))

    async def find_for_decision_role(self, decision_role: str) -> PitchTemplate | None:
        """Return the default template for a decision role, or None."""
        stmt = (
            select(PitchTemplate)
            .where(
                self._base_filter(),
                PitchTemplate.target_decision_role == decision_role,
            )
            .order_by(PitchTemplate.template_id)
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
