"""Brand-deal orchestration: create, patch, set_outcome, and the auto-link
to ``talent.data.previous_brands[]``.

Per the M6 plan (``docs/brand_deals_workflow.md`` § "Relationship to
talent.previous_brands"): when M6 creates a ``brand_deal`` row for a
brand already present as a light entry on ``talent.data.previous_brands[]``,
the create endpoint patches the matching light entry with the new
``deal_id`` FK. Best-effort match: exact ``brand_id`` -> case-insensitive
``brand`` name -> append a new light entry.

Honesty floor (every populated KPI carries ``source`` + ``as_of``) is
enforced by ``app.services.kpi_validation`` and runs on every
``create_deal`` / ``patch_deal`` write.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, date, datetime
from typing import Any

from app.errors import BusinessRuleError, ValidationError
from app.models.sqla.brand import Brand
from app.models.sqla.brand_deal import BrandDeal
from app.repositories.brand import BrandRepository
from app.repositories.brand_deal import BrandDealRepository
from app.repositories.talent import TalentRepository
from app.services.brand_history_enrichment import resolve_industry
from app.services.kpi_validation import validate_deal_payload
from app.utils.logging import get_logger

log = get_logger(__name__)


_DEAL_ID_PATTERN = re.compile(r"^deal_[a-z0-9_]+$")
_BRAND_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _slugify(text: str) -> str:
    """Cheap brand-name -> slug. Mirrors the M5 talent-seed pattern."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "unknown"


def _derive_deal_id(*, brand_id: str, started_at: date | None) -> str:
    """Compose ``deal_<year>_<brand_slug>_<short_hash>`` matching the schema pattern."""
    year = started_at.year if started_at else datetime.now(UTC).year
    suffix = secrets.token_hex(3)
    candidate = f"deal_{year}_{brand_id.replace('-', '_')}_{suffix}"
    if not _DEAL_ID_PATTERN.match(candidate):
        raise BusinessRuleError(f"derived deal_id {candidate!r} does not match required pattern")
    return candidate


def _coerce_started_at(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


class BrandDealService:
    """Orchestrate the deal lifecycle. Mirrors ``TalentOnboardingService`` shape."""

    def __init__(
        self,
        brand_deal_repo: BrandDealRepository,
        talent_repo: TalentRepository,
        brand_repo: BrandRepository,
    ) -> None:
        self._deals = brand_deal_repo
        self._talents = talent_repo
        self._brands = brand_repo

    # ── Create ───────────────────────────────────────────────────────

    async def create_deal(
        self,
        talent_id: str,
        payload: dict[str, Any],
        *,
        agency_id: Any = None,
    ) -> BrandDeal:
        """Create a brand_deal row + auto-link the light entry on talent.data.

        ``payload`` is the deal-level JSON: ``brand_name``/``brand_id``,
        ``industry_id`` (optional — resolved if absent), ``campaign_type``,
        ``deliverables``, ``fee_usd``, ``outcome``, ``kpis``, etc.

        Server-authoritative fields stripped from ``payload``:
        ``deal_id`` (regenerated unless caller supplied a valid one),
        ``first_recorded_at`` (set to now), ``last_updated_at`` (set to now).
        """
        # Confirm the talent exists before we do any LLM / brand work.
        talent_row = await self._talents.get_by_talent_id(talent_id)
        if talent_row is None:
            raise BusinessRuleError(
                f"talent {talent_id!r} not found — cannot create deal",
                detail={"talent_id": talent_id},
            )

        # ── Resolve brand_id + industry_id ──────────────────────────
        brand_id = payload.get("brand_id")
        brand_name = payload.get("brand_name") or payload.get("brand")
        if not brand_name and not brand_id:
            raise ValidationError(
                "deal payload missing both brand_id and brand_name",
                field="brand_name",
            )
        if not brand_id:
            brand_id = _slugify(brand_name)  # type: ignore[arg-type]

        if not _BRAND_SLUG_PATTERN.match(brand_id):
            raise ValidationError(
                f"brand_id {brand_id!r} must match {_BRAND_SLUG_PATTERN.pattern}",
                field="brand_id",
                detail={"received": brand_id},
            )

        industry_id = payload.get("industry_id")
        if not industry_id:
            inference = await resolve_industry(brand_name or brand_id)
            industry_id = inference.industry_id
            if industry_id is None:
                raise ValidationError(
                    "industry_id is required and could not be inferred from brand_name",
                    field="industry_id",
                    detail={"brand_name": brand_name, "brand_id": brand_id},
                )

        # ── Ensure the brand row exists ─────────────────────────────
        existing_brand = await self._brands.get_by_id(brand_id)
        if existing_brand is None:
            stub = Brand(
                brand_id=brand_id,
                name=brand_name or brand_id,
                industry_id=industry_id,
            )
            await self._brands.create_or_skip(stub)

        # ── Compose canonical deal payload ──────────────────────────
        started_at = _coerce_started_at(payload.get("started_at"))
        ended_at = _coerce_started_at(payload.get("ended_at"))
        outcome = payload.get("outcome") or "pending"
        now = datetime.now(UTC)

        deal_id = payload.get("deal_id") or _derive_deal_id(
            brand_id=brand_id, started_at=started_at
        )
        if not _DEAL_ID_PATTERN.match(deal_id):
            raise ValidationError(
                f"deal_id {deal_id!r} must match {_DEAL_ID_PATTERN.pattern}",
                field="deal_id",
            )

        # Strip server-authoritative fields from the JSONB blob.
        data_blob = dict(payload)
        data_blob.update(
            {
                "deal_id": deal_id,
                "brand_id": brand_id,
                "brand_name": brand_name or existing_brand.name if existing_brand else brand_name,
                "industry_id": industry_id,
                "outcome": outcome,
                "first_recorded_at": now.isoformat(),
                "last_updated_at": now.isoformat(),
            }
        )
        data_blob.pop("agency_id", None)

        # ── Honesty-floor validation ────────────────────────────────
        suspicion_flags = validate_deal_payload(data_blob)
        for flag in suspicion_flags:
            log.warning("brand_deal_suspicious_value", deal_id=deal_id, flag=flag)

        # ── Persist the row ─────────────────────────────────────────
        instance = BrandDeal(
            brand_deal_id=deal_id,
            talent_id=talent_id,
            brand_id=brand_id,
            outcome=outcome,
            fee_usd=payload.get("fee_usd"),
            started_at=started_at,
            ended_at=ended_at,
            last_updated_at=now,
            data=data_blob,
        )
        if agency_id is not None:
            instance.agency_id = agency_id
        created = await self._deals.create(instance)

        # ── Auto-link into talent.data.previous_brands[] ────────────
        await self._link_to_previous_brands(
            talent_id=talent_id,
            current=dict(talent_row.data or {}),
            brand_id=brand_id,
            brand_name=brand_name or brand_id,
            industry_id=industry_id,
            deal_id=deal_id,
            campaign_date=ended_at or started_at,
        )

        return created

    # ── Patch ────────────────────────────────────────────────────────

    async def patch_deal(self, deal_id: str, diff: dict[str, Any]) -> BrandDeal:
        """Deep-merge ``diff`` into the deal's JSONB ``data``.

        Server-authoritative fields are stripped from ``diff`` before merge.
        Re-runs the honesty-floor validation on the merged result.
        """
        instance = await self._deals.get_by_id(deal_id)
        if instance is None:
            raise BusinessRuleError(
                f"brand_deal {deal_id!r} not found",
                detail={"brand_deal_id": deal_id},
            )

        sanitised = dict(diff)
        for field in ("deal_id", "first_recorded_at", "last_updated_at", "agency_id"):
            sanitised.pop(field, None)

        # Run validation against the projected merged shape BEFORE writing.
        projected = dict(instance.data or {})
        projected.update(sanitised)
        if "kpis" in sanitised:
            projected["kpis"] = sanitised["kpis"]
        suspicion_flags = validate_deal_payload(projected)
        for flag in suspicion_flags:
            log.warning("brand_deal_suspicious_value", deal_id=deal_id, flag=flag)

        updated = await self._deals.patch_deal_data(deal_id, sanitised)

        # Mirror outcome into the indexed column if the patch touched it.
        new_outcome = sanitised.get("outcome")
        if new_outcome and new_outcome != instance.outcome:
            await self._deals.set_outcome_column(deal_id, str(new_outcome))
        return updated

    # ── Outcome ──────────────────────────────────────────────────────

    async def set_outcome(self, deal_id: str, outcome: str) -> BrandDeal:
        """Set the indexed outcome column AND the JSONB mirror."""
        # Update the indexed column first (fastest), then patch JSONB.
        await self._deals.set_outcome_column(deal_id, outcome)
        return await self._deals.patch_deal_data(deal_id, {"outcome": outcome})

    # ── Memo skeleton ────────────────────────────────────────────────

    async def memo_kpi_pattern(self, deal: BrandDeal) -> None:
        """Emit a memo skeleton so M7 brand-discovery has data to read.

        Real LLM classification of the pattern lands with M7. M6 just
        writes the tagged stub so the cross-talent retrieval path is
        wired end-to-end.

        Best-effort: failures are logged, never raised. The memo write
        path is non-critical compared to the deal persistence itself.
        """
        try:
            import hashlib

            from app.models.sqla.memo import Memo
            from app.repositories.memo import MemoRepository

            data = dict(deal.data or {})
            # ``memo.memo_id`` is ``String(32)``. Derive a stable short id
            # from the deal_id so repeat skeleton writes are idempotent.
            # SHA-256 (not for security — just a stable bucket; usedforsecurity=False).
            short = hashlib.sha256(deal.brand_deal_id.encode(), usedforsecurity=False).hexdigest()[
                :24
            ]
            memo_id = f"kpi_{short}"
            content_lines = [
                f"# KPI pattern for {data.get('brand_name', deal.brand_id)}",
                "",
                f"- talent_id: {deal.talent_id}",
                f"- brand_id: {deal.brand_id}",
                f"- industry_id: {data.get('industry_id')}",
                f"- outcome: {deal.outcome}",
                f"- campaign_type: {data.get('campaign_type')}",
            ]
            memo = Memo(
                memo_id=memo_id,
                memo_type="brand_deal_kpi_pattern",
                scope="industry_pattern",
                content_markdown="\n".join(content_lines),
                tags={
                    "talent_ids": [deal.talent_id],
                    "brand_ids": [deal.brand_id],
                    "industry_ids": [data.get("industry_id")] if data.get("industry_id") else [],
                    "deal_ids": [deal.brand_deal_id],
                    "topics": ["kpi_insight"],
                },
            )
            agency_id = deal.agency_id
            repo = MemoRepository(self._deals._session, agency_id)  # type: ignore[arg-type]
            # Skip writes that already exist — keeps the call idempotent.
            existing = await repo.get_by_id(memo_id)
            if existing is None:
                await repo.create(memo)
        except Exception as exc:
            log.warning(
                "brand_deal_memo_skeleton_failed",
                deal_id=deal.brand_deal_id,
                error=str(exc),
            )

    # ── Internal: auto-link to talent.data.previous_brands[] ─────────

    async def _link_to_previous_brands(
        self,
        *,
        talent_id: str,
        current: dict[str, Any],
        brand_id: str,
        brand_name: str,
        industry_id: str,
        deal_id: str,
        campaign_date: date | None,
    ) -> None:
        """Patch talent.data.previous_brands[] to add the deal_id FK.

        Match priority:
        1. Exact ``brand_id`` match on a light entry that previously got upgraded.
        2. Case-insensitive ``brand`` name match.
        3. No match -> append a new light entry.
        """
        previous = list(current.get("previous_brands") or [])
        match_idx: int | None = None
        for idx, entry in enumerate(previous):
            if not isinstance(entry, dict):
                continue
            if entry.get("brand_id") == brand_id:
                match_idx = idx
                break
        if match_idx is None:
            for idx, entry in enumerate(previous):
                if not isinstance(entry, dict):
                    continue
                entry_name = str(entry.get("brand") or "").strip().lower()
                if entry_name and entry_name == brand_name.strip().lower():
                    match_idx = idx
                    break

        if match_idx is not None:
            updated_entry = dict(previous[match_idx])
            updated_entry["deal_id"] = deal_id
            if "brand_id" not in updated_entry:
                updated_entry["brand_id"] = brand_id
            if industry_id and not updated_entry.get("industry_id"):
                updated_entry["industry_id"] = industry_id
            previous[match_idx] = updated_entry
        else:
            new_entry: dict[str, Any] = {
                "brand": brand_name,
                "brand_id": brand_id,
                "industry_id": industry_id,
                "deal_id": deal_id,
            }
            if campaign_date is not None:
                new_entry["campaign_date"] = campaign_date.isoformat()
            previous.append(new_entry)

        await self._talents.patch_data(talent_id, {"previous_brands": previous})
