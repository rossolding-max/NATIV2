"""``AgencyProfileRepository`` — singleton CRUD for the agency_profile model.

v0.1 is single-agency: there is at most one row. M4 (Phase 0 setup) is the
first consumer that needs to:

- ``get_singleton()`` — fetch the single row (or ``None`` if not yet created).
- ``create_singleton(agency_id, name)`` — write the first row, refusing
  duplicates.
- ``patch_data(agency_id, diff)`` — deep-merge a partial diff into the
  JSONB ``data`` column. Materialised in Python (read-modify-write inside
  a transaction) rather than ``jsonb_set`` SQL — keeps validation, JSONB
  merge, and write semantics in one place that the service layer can hook.
- ``set_status(agency_id, status)`` — flip the status enum.

AgencyProfile is the ROOT of the agency scope, not a child of one — public
methods take ``agency_id`` explicitly and the base-class agency-scoped
filter is bypassed.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import ConflictError, NotFoundError
from app.models.sqla.agency_profile import AgencyProfile
from app.repositories.base import BaseRepository


def _deep_merge(base: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``diff`` into ``base``. Lists are REPLACED, not concatenated.

    Lists-as-replace matches the JSON Schema patch semantics for
    ``agents`` and ``sending_mailboxes`` (where the array IS the value).
    """
    result = deepcopy(base)
    for key, value in diff.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class AgencyProfileRepository(BaseRepository[AgencyProfile]):
    """CRUD + JSONB-patch operations on the singleton ``agency_profile`` row."""

    model = AgencyProfile
    pk_attr = "agency_id"

    def __init__(self, session: AsyncSession, agency_id: UUID | None = None) -> None:
        # AgencyProfile is the ROOT — agency_id binding is loose (None ok at
        # Phase 0 / pre-creation). Pass a sentinel zero-UUID so the base
        # class's __init__ invariants hold; methods take agency_id explicitly.
        super().__init__(session, agency_id or UUID(int=0))

    # ── Singleton operations ─────────────────────────────────────────────

    async def get_singleton(self) -> AgencyProfile | None:
        """Fetch the (at most one) agency_profile row, or ``None``."""
        stmt = select(AgencyProfile).limit(1)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def create_singleton(
        self,
        *,
        agency_id: UUID,
        name: str,
        initial_data: dict[str, Any] | None = None,
    ) -> AgencyProfile:
        """Insert the singleton row. Raises ``ConflictError`` if one already exists."""
        existing = await self.get_singleton()
        if existing is not None:
            raise ConflictError(
                "agency_profile singleton already exists",
                detail={"existing_agency_id": str(existing.agency_id)},
            )
        instance = AgencyProfile(
            agency_id=agency_id,
            name=name,
            status="setup_in_progress",
            data=initial_data or {},
        )
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def patch_data(self, agency_id: UUID, diff: dict[str, Any]) -> AgencyProfile:
        """Deep-merge ``diff`` into the JSONB ``data`` column.

        Read-modify-write inside the caller's transaction. Returns the
        refreshed instance so the service layer can run schema validation
        against the merged result before commit.
        """
        instance = await self._session.get(AgencyProfile, agency_id)
        if instance is None:
            raise NotFoundError(
                f"agency_profile {agency_id} not found",
                detail={"agency_id": str(agency_id)},
            )
        merged = _deep_merge(dict(instance.data or {}), diff)
        instance.data = merged
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def set_status(self, agency_id: UUID, status: str) -> AgencyProfile:
        """Set the ``status`` enum. Caller is responsible for transition rules."""
        stmt = (
            update(AgencyProfile)
            .where(AgencyProfile.agency_id == agency_id)
            .values(status=status)
            .returning(AgencyProfile)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            raise NotFoundError(
                f"agency_profile {agency_id} not found",
                detail={"agency_id": str(agency_id)},
            )
        await self._session.flush()
        return row
