"""``PitchEnrollmentRepository`` — Phase 3b enrollment lookups + state mutations.

Mirrors the M7/M8 repo patterns: ``upsert_run_batch`` + ``patch_workflow_state``
shape, plus state-transition helpers (``set_state``, ``set_killed``) and the
contact-scoped finder used for cross-roster kill (``find_active_for_contact``).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import NotFoundError
from app.models.sqla.pitch_enrollment import PitchEnrollment
from app.repositories.base import BaseRepository

# Workflow-state fields preserved across re-generation runs.
_WORKFLOW_STATE_KEYS: frozenset[str] = frozenset(
    {
        "approved_at",
        "approved_by",
        "killed_at",
        "kill_reason",
        "user_notes",
        "events",
        "engagement_summary",
        "smartlead_meta",
    }
)

_ACTIVE_STATES: frozenset[str] = frozenset({"awaiting_approval", "active", "paused"})


def _deep_merge(base: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    """Mirror BrandCandidateRepository._deep_merge: lists REPLACE, dicts merge."""
    result = deepcopy(base)
    for key, value in diff.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class PitchEnrollmentRepository(BaseRepository[PitchEnrollment]):
    """CRUD + state transitions + workflow patch + active-contact finder."""

    model = PitchEnrollment
    pk_attr = "enrollment_id"

    def __init__(self, session: AsyncSession, agency_id: UUID | None = None) -> None:
        super().__init__(session, agency_id or UUID(int=0))

    # ── Lookups ──────────────────────────────────────────────────────

    async def find_by_talent(
        self,
        talent_id: str,
        *,
        state: str | None = None,
        include_deleted: bool = False,
        limit: int = 200,
    ) -> list[PitchEnrollment]:
        """All enrollments for a talent (most recently updated first)."""
        stmt = select(PitchEnrollment).where(
            self._base_filter(include_deleted=include_deleted),
            PitchEnrollment.talent_id == talent_id,
        )
        if state:
            stmt = stmt.where(PitchEnrollment.state == state)
        stmt = stmt.order_by(
            PitchEnrollment.updated_at.desc().nulls_last(),
            PitchEnrollment.enrollment_id,
        ).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_brand(
        self,
        brand_id: str,
        *,
        include_deleted: bool = False,
        limit: int = 200,
    ) -> list[PitchEnrollment]:
        stmt = (
            select(PitchEnrollment)
            .where(
                self._base_filter(include_deleted=include_deleted),
                PitchEnrollment.brand_id == brand_id,
            )
            .order_by(PitchEnrollment.updated_at.desc().nulls_last())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_active_for_contact(self, contact_id: str) -> list[PitchEnrollment]:
        """All active or awaiting-approval enrollments for a contact (cross-talent).

        Used by cross-roster kill on ``unsubscribe_request`` / hard bounce.
        """
        stmt = (
            select(PitchEnrollment)
            .where(
                self._base_filter(),
                PitchEnrollment.contact_id == contact_id,
                PitchEnrollment.state.in_(list(_ACTIVE_STATES)),
            )
            .order_by(PitchEnrollment.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_state(
        self,
        state: str,
        *,
        limit: int = 500,
    ) -> list[PitchEnrollment]:
        stmt = (
            select(PitchEnrollment)
            .where(self._base_filter(), PitchEnrollment.state == state)
            .order_by(PitchEnrollment.updated_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ── Mutations ────────────────────────────────────────────────────

    async def insert_draft(
        self,
        *,
        enrollment_id: str,
        talent_id: str,
        contact_id: str,
        brand_id: str,
        template_id: str,
        agency_id: UUID,
        data: dict[str, Any],
    ) -> PitchEnrollment:
        """Insert a freshly-generated enrollment in ``awaiting_approval`` state."""
        instance = PitchEnrollment(
            enrollment_id=enrollment_id,
            talent_id=talent_id,
            contact_id=contact_id,
            brand_id=brand_id,
            template_id=template_id,
            state="awaiting_approval",
            data=data,
        )
        instance.agency_id = agency_id
        await self.create(instance)
        return instance

    async def patch_workflow_state(
        self, enrollment_id: str, diff: dict[str, Any]
    ) -> PitchEnrollment:
        """Deep-merge an agent-driven workflow update (state / notes / events)."""
        instance = await self.get_by_id(enrollment_id)
        if instance is None:
            raise NotFoundError(
                f"pitch_enrollment {enrollment_id!r} not found",
                detail={"enrollment_id": enrollment_id},
            )
        sanitised = dict(diff)
        if "state" in sanitised:
            instance.state = str(sanitised["state"])
        if "created_deal_id" in sanitised:
            instance.created_deal_id = sanitised["created_deal_id"]
        merged = _deep_merge(dict(instance.data or {}), sanitised)
        instance.data = merged
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def set_state(
        self,
        enrollment_id: str,
        new_state: str,
        *,
        extra: dict[str, Any] | None = None,
    ) -> PitchEnrollment:
        """Transition state with optional event payload merged into ``data``."""
        diff: dict[str, Any] = {"state": new_state}
        if extra:
            diff.update(extra)
        return await self.patch_workflow_state(enrollment_id, diff)

    async def set_killed(
        self,
        enrollment_id: str,
        *,
        kill_reason: str,
        killed_at: datetime | None = None,
    ) -> PitchEnrollment:
        """Convenience kill: state=killed + killed_at + kill_reason in data."""
        instance = await self.get_by_id(enrollment_id)
        if instance is None:
            raise NotFoundError(
                f"pitch_enrollment {enrollment_id!r} not found",
                detail={"enrollment_id": enrollment_id},
            )
        when = killed_at or datetime.now(UTC)
        instance.state = "killed"
        instance.killed_at = when
        instance.data = _deep_merge(
            dict(instance.data or {}),
            {"kill_reason": kill_reason, "killed_at": when.isoformat()},
        )
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def upsert_step_event(
        self,
        enrollment_id: str,
        step_number: int,
        event: dict[str, Any],
    ) -> PitchEnrollment:
        """Append an engagement event to ``data.events[step_number][]``.

        Idempotent on ``(step_number, event_type, occurred_at)`` — duplicate
        webhook deliveries are no-ops. Returns the updated row.
        """
        instance = await self.get_by_id(enrollment_id)
        if instance is None:
            raise NotFoundError(
                f"pitch_enrollment {enrollment_id!r} not found",
                detail={"enrollment_id": enrollment_id},
            )
        data = dict(instance.data or {})
        events: dict[str, Any] = dict(data.get("events") or {})
        bucket: list[dict[str, Any]] = list(events.get(str(step_number)) or [])
        # Dedup
        key = (event.get("event_type"), event.get("occurred_at"))
        if not any((e.get("event_type"), e.get("occurred_at")) == key for e in bucket):
            bucket.append(event)
        events[str(step_number)] = bucket
        data["events"] = events
        instance.data = data
        await self._session.flush()
        await self._session.refresh(instance)
        return instance
