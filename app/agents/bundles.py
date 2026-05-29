"""Context bundle composer + ``ContextBundle`` Pydantic model.

Per ``architecture.md`` § 6: the bundle composer runs deterministically
BEFORE the agent invocation. Fields vary per pack type; the static prefix
(talent_profile + agency_profile + brand_record) is marked
``cache_control: ephemeral`` for 90%+ token reuse across multi-pass
generation.

M2 ships:
- ``ContextBundle`` Pydantic model with all per-pack-type fields.
- ``compose_for_discovery_prep`` — the M2 example implementation.
- 4 skeleton functions for the other pack types (raise ``NotImplementedError``
  with the owning milestone in the message).

M11-M15 each fill in their pack's composer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import NotFoundError
from app.repositories.agency_profile import AgencyProfileRepository
from app.repositories.brand import BrandRepository
from app.repositories.brand_contact import BrandContactRepository
from app.repositories.brand_deal import BrandDealRepository
from app.repositories.deal import DealRepository
from app.repositories.memo import MemoRepository
from app.repositories.pitch_angle import PitchAngleRepository
from app.repositories.talent import TalentRepository

PackType = Literal[
    "discovery_prep",
    "proposal",
    "contract",
    "invoice",
    "performance_report",
]


class ContextBundleMetadata(BaseModel):
    """Provenance for the bundle. Carried into every Anthropic call."""

    model_config = ConfigDict(extra="forbid")

    pack_type: PackType
    deal_id: str
    agency_id: UUID
    assembled_at: datetime
    assembled_by: str = "deal_orchestrator"


class ContextBundle(BaseModel):
    """Per-pack-type context for the coordinator + skill subagents.

    See ``architecture.md`` § 6 for the per-pack-type field inclusion matrix.
    All entities serialised as ``dict[str, Any]`` (JSON-safe). M2 favours
    flexibility over strict per-field typing; M11+ pack milestones may
    introduce per-pack typed sub-models.
    """

    model_config = ConfigDict(extra="forbid")

    metadata: ContextBundleMetadata

    # Always-included (cacheable as static prefix).
    talent_profile: dict[str, Any]
    agency_profile: dict[str, Any]
    deal_record: dict[str, Any]
    brand_record: dict[str, Any]

    # Pack-type-specific (optional fields).
    brand_contact: dict[str, Any] | None = None
    comparable_brand_deals: list[dict[str, Any]] = Field(default_factory=list)
    top_pitch_angles: list[dict[str, Any]] = Field(default_factory=list)
    originating_enrollment: dict[str, Any] | None = None
    discovery_debrief: dict[str, Any] | None = None
    proposal_pack_snapshot: dict[str, Any] | None = None
    contract_pack_snapshot: dict[str, Any] | None = None
    posting_schedule_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    interim_kpi_snapshots: list[dict[str, Any]] = Field(default_factory=list)

    # Always-included.
    relevant_memos: list[dict[str, Any]] = Field(default_factory=list)

    # Forward-compat (populated by M11 regen flows; None at M2).
    pre_generation_guidance: str | None = None
    regeneration_feedback: str | None = None
    parent_version: int | None = None

    # ── Serialisation helpers ─────────────────────────────────────────

    def static_prefix_text(self) -> str:
        """Return the cacheable static-prefix portion as a text block.

        Includes talent_profile + agency_profile + brand_record + deal_record.
        These are stable across the 3-5 passes within a single pack
        generation, so Anthropic's prompt cache can amortise their cost.
        """
        return (
            "## Context bundle (static prefix — cached)\n\n"
            f"### Talent profile\n{self.talent_profile}\n\n"
            f"### Agency profile\n{self.agency_profile}\n\n"
            f"### Brand record\n{self.brand_record}\n\n"
            f"### Deal record\n{self.deal_record}\n"
        )

    def dynamic_body_text(self) -> str:
        """Return the dynamic-portion text. Not cached."""
        parts = []
        if self.brand_contact:
            parts.append(f"### Brand contact\n{self.brand_contact}")
        if self.comparable_brand_deals:
            n = len(self.comparable_brand_deals)
            parts.append(f"### Comparable brand deals (top {n})\n{self.comparable_brand_deals}")
        if self.top_pitch_angles:
            parts.append(f"### Top pitch angles\n{self.top_pitch_angles}")
        if self.originating_enrollment:
            parts.append(f"### Originating enrollment\n{self.originating_enrollment}")
        if self.discovery_debrief:
            parts.append(f"### Discovery debrief\n{self.discovery_debrief}")
        if self.proposal_pack_snapshot:
            parts.append(f"### Proposal pack (latest)\n{self.proposal_pack_snapshot}")
        if self.contract_pack_snapshot:
            parts.append(f"### Contract pack (latest)\n{self.contract_pack_snapshot}")
        if self.posting_schedule_snapshot:
            parts.append(f"### Posting schedule\n{self.posting_schedule_snapshot}")
        if self.interim_kpi_snapshots:
            parts.append(f"### Interim KPI snapshots\n{self.interim_kpi_snapshots}")
        if self.relevant_memos:
            parts.append(f"### Relevant memos ({len(self.relevant_memos)})\n{self.relevant_memos}")
        return "\n\n".join(parts)


# ── Composer functions ───────────────────────────────────────────────


async def compose_for_discovery_prep(
    session: AsyncSession,
    *,
    deal_id: str,
    agency_id: UUID,
    memo_limit: int = 10,
) -> ContextBundle:
    """Compose the bundle for a Phase 4.5 discovery prep pack generation.

    Reads from the M1 repositories + memo store. Returns a fully-populated
    ContextBundle. Raises ``NotFoundError`` if the deal doesn't exist.

    M2 ships this as the example implementation; M11 (discovery prep
    milestone) may refine the memo retrieval strategy + add Exa research.
    """
    deal_repo = DealRepository(session, agency_id)
    deal = await deal_repo.get_by_id(deal_id)
    if deal is None:
        raise NotFoundError(f"Deal {deal_id} not found in agency {agency_id}")

    talent_repo = TalentRepository(session, agency_id)
    talent = await talent_repo.get_by_id(deal.talent_id)
    if talent is None:
        raise NotFoundError(f"Talent {deal.talent_id} not found")

    brand_repo = BrandRepository(session, agency_id)
    brand = await brand_repo.get_by_id(deal.brand_id)
    if brand is None:
        raise NotFoundError(f"Brand {deal.brand_id} not found")

    # Memo retrieval: brand + industry scope, recent.
    memo_repo = MemoRepository(session, agency_id)
    memos = await memo_repo.find_by_tags(
        brand_ids=[deal.brand_id] if deal.brand_id else None,
        industry_ids=[brand.industry_id] if brand.industry_id else None,
        scope=["brand_relationship", "industry_pattern"],
        limit=memo_limit,
    )

    # M11 — wire the previously-empty placeholder fields.
    agency_repo = AgencyProfileRepository(session, agency_id)
    agency_row = await agency_repo.get_singleton()
    agency_profile_payload: dict[str, Any] = {"agency_id": str(agency_id)}
    if agency_row is not None:
        agency_profile_payload["name"] = agency_row.name
        agency_profile_payload["status"] = agency_row.status
        agency_profile_payload.update(agency_row.data or {})

    brand_contact_payload: dict[str, Any] | None = None
    contact_repo = BrandContactRepository(session, agency_id=agency_id)
    if deal.primary_contact_id:
        contact = await contact_repo.get_by_id(deal.primary_contact_id)
        if contact is not None:
            brand_contact_payload = {
                "contact_id": contact.contact_id,
                "brand_id": contact.brand_id,
                "name": contact.name,
                "decision_role": contact.decision_role,
                "email": contact.email,
                "do_not_contact": bool(contact.do_not_contact),
                **(contact.data or {}),
            }
    if brand_contact_payload is None:
        # Fallback: first non-DNC contact for the brand.
        contacts = await contact_repo.find_by_brand(deal.brand_id, limit=1)
        if contacts:
            c = contacts[0]
            brand_contact_payload = {
                "contact_id": c.contact_id,
                "brand_id": c.brand_id,
                "name": c.name,
                "decision_role": c.decision_role,
                "email": c.email,
                "do_not_contact": bool(c.do_not_contact),
                **(c.data or {}),
            }

    brand_deal_repo = BrandDealRepository(session, agency_id=agency_id)
    raw_brand_deals = await brand_deal_repo.find_by_talent(deal.talent_id, limit=20)
    comparable_brand_deals_payload = [
        {
            "brand_deal_id": d.brand_deal_id,
            "brand_id": d.brand_id,
            "talent_id": d.talent_id,
            "outcome": d.outcome,
            "last_updated_at": d.last_updated_at.isoformat() if d.last_updated_at else None,
            **(d.data or {}),
        }
        for d in raw_brand_deals[:5]
    ]

    pitch_angle_repo = PitchAngleRepository(session, agency_id=agency_id)
    raw_angles = await pitch_angle_repo.find_all()
    top_pitch_angles_payload = [
        {
            "angle_id": a.angle_id,
            "category": a.category,
            "headline": getattr(a, "headline", None),
            "authored_strength_score": float(a.authored_strength_score),
        }
        for a in raw_angles[:5]
    ]

    return ContextBundle(
        metadata=ContextBundleMetadata(
            pack_type="discovery_prep",
            deal_id=deal_id,
            agency_id=agency_id,
            assembled_at=datetime.now(UTC),
        ),
        talent_profile={
            "talent_id": talent.talent_id,
            "name": talent.name,
            "status": talent.status,
            **talent.data,
        },
        agency_profile=agency_profile_payload,
        deal_record={
            "deal_id": deal.deal_id,
            "stage": deal.stage,
            "substage": deal.substage,
            "talent_id": deal.talent_id,
            "brand_id": deal.brand_id,
            **deal.data,
        },
        brand_record={
            "brand_id": brand.brand_id,
            "name": brand.name,
            "industry_id": brand.industry_id,
            **brand.data,
        },
        brand_contact=brand_contact_payload,
        comparable_brand_deals=comparable_brand_deals_payload,
        top_pitch_angles=top_pitch_angles_payload,
        originating_enrollment=None,  # M11.1 — wire from deal.originating_enrollment_id
        relevant_memos=[
            {
                "memo_id": m.memo_id,
                "memo_type": m.memo_type,
                "scope": m.scope,
                "content_markdown": m.content_markdown,
                "tags": m.tags,
            }
            for m in memos
        ],
    )


def _not_implemented(pack_type: PackType, milestone: str) -> None:
    """Helper for the 4 deferred pack composers."""
    raise NotImplementedError(f"compose_for_{pack_type}: implementation lands in {milestone}")


async def compose_for_proposal(*_args: Any, **_kwargs: Any) -> ContextBundle:
    """Proposal pack composer — lands in M12 (proposal milestone)."""
    _not_implemented("proposal", "M12")
    raise AssertionError("unreachable")  # for type-checker


async def compose_for_contract(*_args: Any, **_kwargs: Any) -> ContextBundle:
    """Contract pack composer — lands in M13 (contract milestone)."""
    _not_implemented("contract", "M13")
    raise AssertionError("unreachable")


async def compose_for_invoice(*_args: Any, **_kwargs: Any) -> ContextBundle:
    """Invoice pack composer — lands in M14 (invoice milestone)."""
    _not_implemented("invoice", "M14")
    raise AssertionError("unreachable")


async def compose_for_performance_report(*_args: Any, **_kwargs: Any) -> ContextBundle:
    """Performance report composer — lands in M15 (perf report milestone)."""
    _not_implemented("performance_report", "M15")
    raise AssertionError("unreachable")
