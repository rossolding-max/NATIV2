"""``DealRepository`` — Phase 4 deal lifecycle.

M9 owns the GAP-06 bidirectional-FK INSERT path. M10 adds:

- Read-side finders (``find_by_talent``, ``find_by_brand``,
  ``find_by_stage``, ``find_due_for_action``).
- Pipeline scanners for the two M10 Celery tasks
  (``find_ready_for_prep_pack``, ``find_ready_for_archive``).
- ``patch_workflow_state`` with guard rails: refuses ``substage="lost"``
  (must go through orchestrator ``record_loss``) and direct ``stage``
  writes (must go through orchestrator ``apply_transition``); allows the
  workflow scalars + the schema's whitelisted nested paths (Tier-1 G2
  fix: ``data.delivery.campaign_hashtags[]``).
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import BusinessRuleError, NotFoundError
from app.models.sqla.deal import Deal
from app.repositories.base import BaseRepository

# Top-level Deal columns the agent is allowed to touch via PATCH.
# Stage / substage / is_terminal / is_won are off-limits (use the
# orchestrator transition path).
_ALLOWED_TOP_LEVEL: frozenset[str] = frozenset(
    {
        "next_action_due_at",
        "expected_value_usd",
        "expected_close_date",
        "primary_contact_id",
    }
)

# JSONB nested paths the agent can write via PATCH. Each is checked
# against the diff dict's keys for ``data``.
_ALLOWED_DATA_KEYS: frozenset[str] = frozenset(
    {
        "user_notes",
        "lead",
        "proposal",
        "contract",
        "delivery",  # Tier-1 G2: includes campaign_hashtags[]
        "close",
        "attachments",
        "notes",
        "next_action",
    }
)


def _deep_merge(base: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    """Mirror M7/M8/M9 _deep_merge: lists REPLACE, dicts merge."""
    result = deepcopy(base)
    for key, value in diff.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class DealRepository(BaseRepository[Deal]):
    """Deal-lifecycle CRUD + finders + guarded patch."""

    model = Deal
    pk_attr = "deal_id"

    def __init__(self, session: AsyncSession, agency_id: UUID | None = None) -> None:
        super().__init__(session, agency_id or UUID(int=0))

    # ── Lookups ──────────────────────────────────────────────────────

    async def find_by_enrollment(self, enrollment_id: str) -> Deal | None:
        stmt = select(Deal).where(
            self._base_filter(),
            Deal.originating_enrollment_id == enrollment_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_talent(
        self,
        talent_id: str,
        *,
        stage: str | None = None,
        substage: str | None = None,
        include_terminal: bool = False,
        limit: int = 200,
    ) -> list[Deal]:
        stmt = select(Deal).where(
            self._base_filter(),
            Deal.talent_id == talent_id,
        )
        if stage:
            stmt = stmt.where(Deal.stage == stage)
        if substage:
            stmt = stmt.where(Deal.substage == substage)
        if not include_terminal:
            stmt = stmt.where(Deal.is_terminal == false())
        stmt = stmt.order_by(Deal.updated_at.desc().nulls_last(), Deal.deal_id).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_brand(
        self,
        brand_id: str,
        *,
        include_terminal: bool = False,
        limit: int = 200,
    ) -> list[Deal]:
        stmt = select(Deal).where(
            self._base_filter(),
            Deal.brand_id == brand_id,
        )
        if not include_terminal:
            stmt = stmt.where(Deal.is_terminal == false())
        stmt = stmt.order_by(Deal.updated_at.desc().nulls_last()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_stage(self, stage: str, *, limit: int = 500) -> list[Deal]:
        stmt = (
            select(Deal)
            .where(self._base_filter(), Deal.stage == stage)
            .order_by(Deal.updated_at.desc().nulls_last())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_due_for_action(
        self, now: datetime, *, talent_id: str | None = None, limit: int = 500
    ) -> list[Deal]:
        """Non-terminal deals where ``next_action_due_at <= now``."""
        stmt = select(Deal).where(
            self._base_filter(),
            Deal.is_terminal == false(),
            Deal.next_action_due_at.is_not(None),
            Deal.next_action_due_at <= now,
        )
        if talent_id:
            stmt = stmt.where(Deal.talent_id == talent_id)
        stmt = stmt.order_by(Deal.next_action_due_at.asc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_ready_for_prep_pack(self, *, limit: int = 50) -> list[Deal]:
        """Deals at ``initial_call_scheduled`` with no prep pack enqueued yet.

        Debounces on ``data.prep_pack_enqueued_at`` so the 5-min cron
        doesn't re-enqueue while M11's generator is running.
        """
        stmt = (
            select(Deal)
            .where(
                self._base_filter(),
                Deal.substage == "initial_call_scheduled",
                Deal.latest_prep_pack_id.is_(None),
                Deal.is_terminal == false(),
            )
            .order_by(Deal.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        deals = list(result.scalars().all())
        # Filter on the JSONB debounce stamp in Python; doing it in SQL
        # against the in-flight nested-key path is ugly and the candidate
        # set is small.
        return [d for d in deals if _enqueue_stale(d.data)]

    async def find_ready_for_archive(self, *, limit: int = 50) -> list[Deal]:
        """Deals where the 3 close-gate flags are all set + substage != archived."""
        # All three gates live in ``data.close`` so we filter in SQL by
        # ``post_campaign_reporting`` substage (the only one feeding archive)
        # then verify the 3 keys in Python.
        stmt = (
            select(Deal)
            .where(
                self._base_filter(),
                Deal.substage == "post_campaign_reporting",
                Deal.is_terminal == false(),
            )
            .order_by(Deal.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        deals = list(result.scalars().all())
        return [d for d in deals if _archive_gates_met(d.data)]

    # ── Mutations ────────────────────────────────────────────────────

    async def patch_workflow_state(self, deal_id: str, diff: dict[str, Any]) -> Deal:
        """Deep-merge an agent workflow patch.

        Guards: refuses direct ``stage`` writes (use ``record_transition``
        instead) and refuses ``substage="lost"`` (use the orchestrator's
        ``record_loss``). All other top-level scalar columns + the
        ``data`` JSONB are mergeable per the allow-lists.
        """
        instance = await self.get_by_id(deal_id)
        if instance is None:
            raise NotFoundError(f"deal {deal_id!r} not found", detail={"deal_id": deal_id})
        _validate_workflow_diff(diff)

        for key in _ALLOWED_TOP_LEVEL:
            if key in diff:
                setattr(instance, key, diff[key])

        data_diff: dict[str, Any] | None = None
        if "data" in diff and isinstance(diff["data"], dict):
            data_diff = {k: v for k, v in diff["data"].items() if k in _ALLOWED_DATA_KEYS}
        if data_diff:
            instance.data = _deep_merge(dict(instance.data or {}), data_diff)

        await self._session.flush()
        await self._session.refresh(instance)
        return instance

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
        """M9 entry point — INSERT a lead-stage deal from an interested reply.

        Companion ``pitch_enrollment.created_deal_id`` UPDATE is the
        caller's job (GAP-06 single-transaction guarantee).
        """
        bound = agency_id or self._agency_id
        deal_id = f"deal_pipeline_{uuid4().hex[:24]}"
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

    async def insert_manual_deal(
        self,
        *,
        talent_id: str,
        brand_id: str,
        primary_contact_id: str | None,
        by_agent_id: str,
        agency_id: UUID | None = None,
        opening_note: str | None = None,
        created_at: datetime | None = None,
    ) -> Deal:
        """Manual ``POST /deals`` create — lands in ``lead/new_lead``.

        Writes an opening ``stage_history`` entry so the audit log starts
        at row 1.
        """
        bound = agency_id or self._agency_id
        when = created_at or datetime.now(UTC)
        deal_id = f"deal_pipeline_{uuid4().hex[:24]}"
        data: dict[str, Any] = {
            "stage_history": [
                {
                    "stage": "lead",
                    "substage": "new_lead",
                    "at": when.isoformat(),
                    "by_agent_id": by_agent_id,
                    "note": opening_note or "manual creation",
                }
            ]
        }
        instance = Deal(
            deal_id=deal_id,
            talent_id=talent_id,
            brand_id=brand_id,
            primary_contact_id=primary_contact_id,
            stage="lead",
            substage="new_lead",
            data=data,
        )
        instance.agency_id = bound
        await self.create(instance)
        return instance


# ── Helpers ─────────────────────────────────────────────────────────


def _validate_workflow_diff(diff: dict[str, Any]) -> None:
    """Raise on any forbidden key in the patch diff."""
    if "stage" in diff:
        raise BusinessRuleError(
            "direct stage writes are not allowed; use POST /deals/{id}/transition",
            detail={"forbidden": "stage"},
        )
    if "substage" in diff:
        raise BusinessRuleError(
            "direct substage writes are not allowed; use POST /deals/{id}/transition",
            detail={"forbidden": "substage"},
        )
    if "is_terminal" in diff or "is_won" in diff:
        raise BusinessRuleError(
            "is_terminal / is_won are derived; use the transition or loss endpoints",
            detail={"forbidden": "is_terminal/is_won"},
        )
    if "data" in diff and isinstance(diff["data"], dict):
        if diff["data"].get("loss") is not None:
            raise BusinessRuleError(
                "use POST /deals/{id}/loss to capture a structured loss reason",
                detail={"forbidden": "data.loss"},
            )
        if "stage_history" in diff["data"]:
            raise BusinessRuleError(
                "stage_history is append-only; rejected from PATCH diff",
                detail={"forbidden": "data.stage_history"},
            )


def _enqueue_stale(data: dict[str, Any] | None) -> bool:
    """Debounce: skip deals enqueued within the last hour."""
    if not data:
        return True
    stamp = data.get("prep_pack_enqueued_at")
    if not stamp:
        return True
    if isinstance(stamp, datetime):
        ts = stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)
    elif isinstance(stamp, str):
        try:
            ts = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            return True
    else:
        return True
    return ts < datetime.now(UTC) - timedelta(hours=1)


def _archive_gates_met(data: dict[str, Any] | None) -> bool:
    """Return True when all three M16 archive gates are set."""
    close = (data or {}).get("close") or {}
    if not isinstance(close, dict):
        return False
    return (
        bool(close.get("all_invoices_paid_at"))
        and bool(close.get("final_kpis"))
        and bool(close.get("final_performance_report_attachment_id"))
    )
