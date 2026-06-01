"""``BrandContactRepository`` — Phase 3a enrichment upsert + workflow patch.

Mirrors the M7 ``BrandCandidateRepository`` shape:
- ``upsert_run_batch`` — per-run insert/update. Workflow-state fields
  (``do_not_contact``, ``opt_out_at``, ``pitch_history``, ``tags``,
  ``notes``) are preserved across enrichment runs; everything else is
  overwritten as fresh enrichment output.
- ``patch_workflow_state`` — REST PATCH path; agent-driven updates to
  the preserved fields without re-running enrichment.
- ``set_scalar_columns`` — keeps the scalar mirror columns
  (``decision_role``, ``email``, ``do_not_contact``) in sync with the
  JSONB ``data`` payload.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import NotFoundError
from app.models.sqla.brand_contact import BrandContact
from app.repositories.base import BaseRepository

# Workflow-state fields preserved across enrichment runs (per
# docs/contact_enrichment_workflow.md). Anything outside this set is
# treated as enrichment output and overwritten each run.
_WORKFLOW_STATE_KEYS: frozenset[str] = frozenset(
    {
        "do_not_contact",
        "do_not_contact_reason",
        "opt_out_at",
        "pitch_history",
        "tags",
        "notes",
        "champion_for_talents",
        "first_discovered_at",
    }
)


def _deep_merge(base: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    """Mirror BrandCandidateRepository._deep_merge: lists REPLACE, dicts merge."""
    result = deepcopy(base)
    for key, value in diff.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class BrandContactRepository(BaseRepository[BrandContact]):
    """CRUD + enrichment upsert + workflow patch + scalar-mirror sync."""

    model = BrandContact
    pk_attr = "contact_id"

    def __init__(self, session: AsyncSession, agency_id: UUID | None = None) -> None:
        super().__init__(session, agency_id or UUID(int=0))

    # ── Lookups ──────────────────────────────────────────────────────

    async def find_by_brand(
        self,
        brand_id: str,
        *,
        include_deleted: bool = False,
        limit: int = 200,
    ) -> list[BrandContact]:
        """All contacts for a brand (most recently updated first)."""
        stmt = (
            select(BrandContact)
            .where(
                self._base_filter(include_deleted=include_deleted),
                BrandContact.brand_id == brand_id,
            )
            .order_by(BrandContact.updated_at.desc().nulls_last(), BrandContact.contact_id)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_pitchable_for_talent(
        self,
        talent_id: str,
        brand_id: str,
        *,
        include_deleted: bool = False,
    ) -> list[BrandContact]:
        """Contacts at a brand that ARE pitchable for the given talent right now.

        Filters out ``do_not_contact=True`` rows; per-talent 14-day
        cooldown filtering is left to ``policy_filter.apply_contact_filters``
        because the cutoff depends on ``today`` and is run-time logic.
        """
        stmt = (
            select(BrandContact)
            .where(
                self._base_filter(include_deleted=include_deleted),
                BrandContact.brand_id == brand_id,
                BrandContact.do_not_contact.is_(False),
            )
            .order_by(BrandContact.updated_at.desc().nulls_last())
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        # Cooldown check: drop contacts where this talent pitched within
        # the last 14 days (policy_filter has the real logic; here we
        # do the simple drop-by-recent-pitch-existence pass).
        return [r for r in rows if not _was_recently_pitched(r.data, talent_id)]

    async def get_by_brand_and_contact(self, brand_id: str, contact_id: str) -> BrandContact | None:
        stmt = select(BrandContact).where(
            self._base_filter(),
            BrandContact.brand_id == brand_id,
            BrandContact.contact_id == contact_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Mutations ────────────────────────────────────────────────────

    @staticmethod
    def set_scalar_columns(row: BrandContact, contact_data: dict[str, Any]) -> None:
        """Sync indexed scalar columns from JSONB.

        Covers: ``decision_role``, ``outreach_recommendation`` (M8.1),
        ``email``, ``do_not_contact``. Idempotent — call after every
        JSONB write so the indexed scalar columns stay consistent.

        ``revealed_at`` is NOT synced here — it's only ever set by
        ``update_email_reveal()`` after a successful Phase C reveal
        attempt, never overwritten by ordinary Phase A enrichment writes.
        """
        role = contact_data.get("decision_role")
        if isinstance(role, str) and role.strip():
            row.decision_role = role.strip().lower()
        # M8.1 — outreach_recommendation flag from extended Step 6 LLM call.
        recommendation = contact_data.get("outreach_recommendation")
        if isinstance(recommendation, str) and recommendation.strip():
            row.outreach_recommendation = recommendation.strip().lower()
        email = contact_data.get("email")
        if isinstance(email, dict):
            address = email.get("address")
            row.email = address if isinstance(address, str) and address.strip() else None
        elif isinstance(email, str):
            row.email = email.strip() or None
        dnc = contact_data.get("do_not_contact")
        if isinstance(dnc, bool):
            row.do_not_contact = dnc

    async def upsert_run_batch(
        self,
        brand_id: str,
        contact_payloads: list[dict[str, Any]],
        *,
        agency_id: UUID | None = None,
    ) -> list[BrandContact]:
        """Insert new rows + update enrichment fields on existing rows.

        Workflow-state fields are preserved per ``_WORKFLOW_STATE_KEYS``.
        """
        bound_agency_id = agency_id or self._agency_id
        upserted: list[BrandContact] = []
        for payload in contact_payloads:
            contact_id = payload.get("contact_id")
            if not contact_id:
                continue
            existing = await self.get_by_brand_and_contact(brand_id, contact_id)
            new_data = {k: v for k, v in payload.items() if k not in {"contact_id", "brand_id"}}
            name = payload.get("name") or "Unknown"

            if existing is None:
                instance = BrandContact(
                    contact_id=contact_id,
                    brand_id=brand_id,
                    name=str(name)[:200],
                    data=new_data,
                )
                instance.agency_id = bound_agency_id
                self.set_scalar_columns(instance, new_data)
                await self.create(instance)
                upserted.append(instance)
            else:
                existing_data: dict[str, Any] = dict(existing.data or {})
                preserved = {
                    k: existing_data[k] for k in _WORKFLOW_STATE_KEYS if k in existing_data
                }
                merged_data = _deep_merge(dict(new_data), preserved)
                existing.data = merged_data
                existing.name = str(name)[:200]
                # Re-sync scalar columns from merged data (preserved
                # do_not_contact must win over any fresh enrichment value).
                self.set_scalar_columns(existing, merged_data)
                await self._session.flush()
                await self._session.refresh(existing)
                upserted.append(existing)
        return upserted

    async def patch_workflow_state(self, contact_id: str, diff: dict[str, Any]) -> BrandContact:
        """Deep-merge an agent-driven workflow update."""
        instance = await self.get_by_id(contact_id)
        if instance is None:
            raise NotFoundError(
                f"brand_contact {contact_id!r} not found",
                detail={"contact_id": contact_id},
            )
        merged_data = _deep_merge(dict(instance.data or {}), diff)
        instance.data = merged_data
        self.set_scalar_columns(instance, merged_data)
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    # ── M8.1 — Phase C email reveal ──────────────────────────────────

    async def update_email_reveal(
        self,
        contact_id: str,
        *,
        email_address: str | None,
        verification_status: str | None,
        revealed_at: datetime,
    ) -> BrandContact:
        """Write the outcome of one Apollo /people/match reveal attempt.

        Called per-contact from ``step_5b_reveal_email`` after the
        operator triggers Phase C bulk reveal. Sets the scalar ``email``
        + ``revealed_at`` columns AND merges the verification status
        into the JSONB ``data.email`` block so the M8 schema audit
        trail (``verification_status``, ``verification_sources``) stays
        intact.

        ``email_address=None`` is a valid input — captures "reveal
        attempted, no verified email returned"; the row's ``revealed_at``
        still moves forward so the UI shows we tried.
        """
        instance = await self.get_by_id(contact_id)
        if instance is None:
            raise NotFoundError(
                f"brand_contact {contact_id!r} not found",
                detail={"contact_id": contact_id},
            )
        merged_data = dict(instance.data or {})
        email_block = dict(merged_data.get("email") or {})
        if email_address:
            email_block["address"] = email_address
        if verification_status:
            email_block["verification_status"] = verification_status
        if email_block:
            merged_data["email"] = email_block
        instance.data = merged_data
        instance.email = email_address or None
        instance.revealed_at = revealed_at
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def find_unrevealed_by_brand(self, brand_id: str) -> list[BrandContact]:
        """Return contacts at a brand whose Phase C reveal hasn't fired yet.

        Drives the UI "show me contacts ready for email reveal" filter.
        ``revealed_at IS NULL`` means no reveal attempt; ``revealed_at
        IS NOT NULL`` means an attempt happened (regardless of whether
        an email came back).
        """
        stmt = select(BrandContact).where(
            BrandContact.brand_id == brand_id,
            BrandContact.is_deleted.is_(False),
            BrandContact.revealed_at.is_(None),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


def _was_recently_pitched(data: dict[str, Any] | None, talent_id: str, *, days: int = 14) -> bool:
    """Cheap pre-filter for ``find_pitchable_for_talent``.

    Returns True if any ``pitch_history`` entry for this talent exists.
    The strict day-window check is done in ``policy_filter``; this is a
    coarse filter to avoid pulling obviously-recent rows back.
    """
    from datetime import UTC, datetime, timedelta

    if not data:
        return False
    history = data.get("pitch_history") or []
    if not isinstance(history, list):
        return False
    cutoff = datetime.now(UTC) - timedelta(days=days)
    for entry in history:
        if not isinstance(entry, dict):
            continue
        if entry.get("talent_id") != talent_id:
            continue
        ts = entry.get("created_at") or entry.get("sent_at")
        if not isinstance(ts, str):
            continue
        try:
            from datetime import datetime as _dt

            parsed = _dt.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed >= cutoff:
            return True
    return False
