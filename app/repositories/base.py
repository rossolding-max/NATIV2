"""Generic async repository base.

Per ``docs/code_conventions.md`` § 12.2 + the M1 plan: every domain
repository inherits ``BaseRepository[Model]`` and gets standard CRUD with
``agency_id`` filter enforcement at the repo layer (single source of
truth — the v2 multi-tenant bridge).

Construct via the FastAPI dep factory pattern:

    def get_talent_repo(
        session: AsyncSession = Depends(get_db),
        agency_id: UUID = Depends(require_agency_id),
    ) -> TalentRepository:
        return TalentRepository(session, agency_id)

Non-API callers (Celery tasks, agents in M2) pass ``agency_id`` directly:

    repo = TalentRepository(session, agency_id=some_uuid)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, true, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.errors import BusinessRuleError, NotFoundError


class BaseRepository[ModelT: Base]:
    """Generic async CRUD repository scoped to a single agency."""

    model: type[ModelT]
    """Concrete subclass sets this to the SQLA model class it manages."""

    pk_attr: str = ""
    """Name of the model's primary key attribute. Concrete subclass overrides."""

    def __init__(self, session: AsyncSession, agency_id: UUID) -> None:
        if not self.model:
            raise BusinessRuleError(
                f"{type(self).__name__} must set `model = SomeModel` class attribute"
            )
        if not self.pk_attr:
            raise BusinessRuleError(
                f"{type(self).__name__} must set `pk_attr = 'name_of_pk'` class attribute"
            )
        self._session = session
        self._agency_id = agency_id

    # ── Default filter ─────────────────────────────────────────────────

    def _base_filter(self, *, include_deleted: bool = False) -> Any:
        """Build the standard WHERE clause: agency_id match + soft-delete filter.

        Subclasses for global tables (e.g. `BrandRepository`) override to drop
        the agency_id constraint.
        """
        stmt = true()
        if hasattr(self.model, "agency_id"):
            stmt = stmt & (self.model.agency_id == self._agency_id)  # type: ignore[attr-defined]
        if not include_deleted and hasattr(self.model, "is_deleted"):
            stmt = stmt & (self.model.is_deleted.is_(False))  # type: ignore[attr-defined]
        return stmt

    # ── CRUD ───────────────────────────────────────────────────────────

    async def get_by_id(self, pk: str, *, include_deleted: bool = False) -> ModelT | None:
        """Return the row matching ``pk`` for the bound agency, or ``None``."""
        col = getattr(self.model, self.pk_attr)
        stmt = select(self.model).where(
            self._base_filter(include_deleted=include_deleted),
            col == pk,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_agency(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        include_deleted: bool = False,
    ) -> list[ModelT]:
        """List rows for the bound agency. Offset paginated (v0.1)."""
        stmt = (
            select(self.model)
            .where(self._base_filter(include_deleted=include_deleted))
            .order_by(getattr(self.model, self.pk_attr))
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, *, include_deleted: bool = False) -> int:
        """Return the count of rows for the bound agency."""
        from sqlalchemy import func

        stmt = (
            select(func.count())
            .select_from(self.model)
            .where(self._base_filter(include_deleted=include_deleted))
        )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def create(self, instance: ModelT) -> ModelT:
        """Add + flush a new instance. Caller commits."""
        # Enforce agency_id binding on agency-scoped models.
        if hasattr(self.model, "agency_id") and getattr(instance, "agency_id", None) is None:
            instance.agency_id = self._agency_id  # type: ignore[attr-defined]
        self._session.add(instance)
        await self._session.flush()
        return instance

    async def soft_delete(self, pk: str, *, deleted_by_agent_id: str) -> ModelT:
        """Mark a row deleted. Returns the soft-deleted instance."""
        instance = await self.get_by_id(pk)
        if instance is None:
            raise NotFoundError(f"{self.model.__name__} {pk!r} not found")
        instance.is_deleted = True  # type: ignore[attr-defined]
        instance.deleted_at = datetime.now(UTC)  # type: ignore[attr-defined]
        instance.deleted_by_agent_id = deleted_by_agent_id  # type: ignore[attr-defined]
        await self._session.flush()
        return instance

    async def update_fields(self, pk: str, **fields: Any) -> ModelT:
        """Update a row's scalar fields in-place. Returns the refreshed instance."""
        instance = await self.get_by_id(pk)
        if instance is None:
            raise NotFoundError(f"{self.model.__name__} {pk!r} not found")
        col = getattr(self.model, self.pk_attr)
        stmt = update(self.model).where(self._base_filter(), col == pk).values(**fields)
        await self._session.execute(stmt)
        await self._session.flush()
        await self._session.refresh(instance)
        return instance
