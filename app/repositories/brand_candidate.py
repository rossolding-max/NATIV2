"""``BrandCandidateRepository`` — discovery upsert + workflow-state patch.

The repo handles the two write paths M7 needs:
- ``upsert_run_batch`` — the orchestrator's per-run write. Inserts new
  ``brand_candidate`` rows for newly-surfaced brands, updates the
  discovery-output fields (score, tier, JSONB ``data`` sources +
  qualification) for ones that already exist, BUT leaves workflow-state
  fields (status, JSONB pitch_history / user_notes / etc.) alone.
- ``patch_workflow_state`` — the REST PATCH endpoint, where the agent
  updates status / notes / pitch_history without re-running discovery.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import NotFoundError
from app.models.sqla.brand_candidate import BrandCandidate
from app.repositories.base import BaseRepository

# Workflow-state fields preserved across discovery runs (per
# docs/brand_discovery.md § "Preserved fields"). Anything not in this
# set is treated as discovery output and overwritten on each run.
_WORKFLOW_STATE_KEYS: frozenset[str] = frozenset(
    {
        "status",
        "assigned_to",
        "user_notes",
        "pitch_history",
        "legal_entity_override",
        "first_surfaced_at",
    }
)


def _deep_merge(base: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    """Mirror TalentRepository._deep_merge: lists REPLACE, dicts merge."""
    result = deepcopy(base)
    for key, value in diff.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


class BrandCandidateRepository(BaseRepository[BrandCandidate]):
    """CRUD + discovery upsert + workflow patch."""

    model = BrandCandidate
    pk_attr = "candidate_id"

    def __init__(self, session: AsyncSession, agency_id: UUID | None = None) -> None:
        super().__init__(session, agency_id or UUID(int=0))

    # ── Lookups ──────────────────────────────────────────────────────

    async def find_by_talent(
        self,
        talent_id: str,
        *,
        include_deleted: bool = False,
        limit: int = 500,
    ) -> list[BrandCandidate]:
        """All candidates for a talent (alphabetical by brand_id).

        M7.4 — sort is neutral so score / tier don't smuggle in a
        ranking. Score is still on every row for callers that want to
        re-order client-side.
        """
        stmt = (
            select(BrandCandidate)
            .where(
                self._base_filter(include_deleted=include_deleted),
                BrandCandidate.talent_id == talent_id,
            )
            .order_by(BrandCandidate.brand_id)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_tier(
        self,
        talent_id: str,
        tier: str,
        *,
        include_deleted: bool = False,
    ) -> list[BrandCandidate]:
        """Per-talent filter on the indexed ``tier`` column (alphabetical)."""
        stmt = (
            select(BrandCandidate)
            .where(
                self._base_filter(include_deleted=include_deleted),
                BrandCandidate.talent_id == talent_id,
                BrandCandidate.tier == tier,
            )
            .order_by(BrandCandidate.brand_id)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_talent_and_brand(self, talent_id: str, brand_id: str) -> BrandCandidate | None:
        stmt = select(BrandCandidate).where(
            self._base_filter(),
            BrandCandidate.talent_id == talent_id,
            BrandCandidate.brand_id == brand_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Mutations ────────────────────────────────────────────────────

    async def upsert_run_batch(
        self,
        talent_id: str,
        candidate_payloads: list[dict[str, Any]],
        *,
        agency_id: UUID | None = None,
    ) -> list[BrandCandidate]:
        """Insert new rows + update discovery-output fields on existing rows.

        ``candidate_payloads`` is the list of dicts produced by the
        orchestrator (one per QualifiedCandidate, already serialised via
        ``snapshot._candidate_to_dict``). The repo handles the
        discovery vs workflow-state split: only discovery output is
        overwritten; status / notes / pitch_history survive.
        """
        bound_agency_id = agency_id or self._agency_id
        upserted: list[BrandCandidate] = []
        for payload in candidate_payloads:
            brand_id = payload.get("brand_id")
            if not brand_id:
                continue
            existing = await self.get_by_talent_and_brand(talent_id, brand_id)

            tier = payload.get("tier") or "tertiary"
            score = payload.get("score")
            new_data = {k: v for k, v in payload.items() if k not in {"brand_id"}}
            if existing is None:
                instance = BrandCandidate(
                    candidate_id=f"bc_{uuid4().hex[:24]}",
                    talent_id=talent_id,
                    brand_id=brand_id,
                    tier=tier,
                    status=str(payload.get("status") or "new"),
                    score=score,
                    data=new_data,
                )
                instance.agency_id = bound_agency_id
                await self.create(instance)
                upserted.append(instance)
            else:
                # Discovery-output overwrite; workflow-state preserved.
                existing_data: dict[str, Any] = dict(existing.data or {})
                preserved = {
                    k: existing_data[k] for k in _WORKFLOW_STATE_KEYS if k in existing_data
                }
                merged_data = _deep_merge(dict(new_data), preserved)
                existing.tier = tier
                if score is not None:
                    existing.score = score
                existing.data = merged_data
                await self._session.flush()
                await self._session.refresh(existing)
                upserted.append(existing)
        return upserted

    async def patch_workflow_state(self, candidate_id: str, diff: dict[str, Any]) -> BrandCandidate:
        """Deep-merge an agent-driven workflow update (status / notes / pitch_history)."""
        instance = await self.get_by_id(candidate_id)
        if instance is None:
            raise NotFoundError(
                f"brand_candidate {candidate_id!r} not found",
                detail={"candidate_id": candidate_id},
            )
        # ``status`` may be in the diff as a top-level column AND inside
        # the JSONB data — keep both in sync.
        sanitised = dict(diff)
        if "status" in sanitised:
            instance.status = str(sanitised["status"])
        merged_data = _deep_merge(dict(instance.data or {}), sanitised)
        instance.data = merged_data
        await self._session.flush()
        await self._session.refresh(instance)
        return instance
