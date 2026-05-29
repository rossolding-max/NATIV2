"""Apply a state-machine transition + sync scalar columns + audit-log.

Both ``apply_transition`` and ``record_loss`` mutate the passed-in
``Deal`` instance in place (deep-merging JSONB ``data`` + updating
scalar mirror columns). The caller flushes + commits.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from app.models.sqla.deal import Deal
from app.services.deal_lifecycle.loss_reasons import (
    lost_at_stage_for,
    validate_reason,
)
from app.services.deal_lifecycle.state_machine import (
    StageTransitionPlan,
    transition,
)
from app.services.deal_lifecycle.transitions import TERMINAL_SUBSTAGES, WON_SUBSTAGE


def _append_stage_history(
    data: dict[str, Any],
    *,
    stage: str,
    substage: str,
    by_agent_id: str,
    at: datetime,
    note: str | None,
) -> None:
    history: list[dict[str, Any]] = list(data.get("stage_history") or [])
    entry: dict[str, Any] = {
        "stage": stage,
        "substage": substage,
        "at": at.isoformat(),
        "by_agent_id": by_agent_id,
    }
    if note:
        entry["note"] = note
    history.append(entry)
    data["stage_history"] = history


def apply_transition(
    *,
    deal: Deal,
    target_substage: str,
    by_agent_id: str,
    note: str | None = None,
    now: datetime | None = None,
) -> StageTransitionPlan:
    """Mutate ``deal`` to land on ``target_substage`` (possibly via auto-advance).

    Returns the executed plan so the caller can echo the chain in the
    REST response. Does NOT call ``session.flush()`` — that's the
    caller's job (so transactional boundaries stay with the request handler).
    """
    plan = transition(
        current_stage=deal.stage,
        current_substage=deal.substage,
        target_substage=target_substage,
        by_agent_id=by_agent_id,
        note=note,
    )
    when = now or datetime.now(UTC)
    data: dict[str, Any] = deepcopy(dict(deal.data or {}))
    # Apply each step sequentially so an auto-advance gets its own
    # audit-log entry.
    for step in plan.steps:
        _append_stage_history(
            data,
            stage=step.stage,
            substage=step.substage,
            by_agent_id=step.by_agent_id,
            at=when,
            note=step.note,
        )
        deal.stage = step.stage
        deal.substage = step.substage
    deal.is_terminal = plan.final_is_terminal
    deal.is_won = plan.final_is_won
    deal.data = data
    return plan


def record_loss(
    *,
    deal: Deal,
    reason: str,
    by_agent_id: str,
    lost_at_stage: str | None = None,
    competitor_brand: str | None = None,
    notes: str | None = None,
    now: datetime | None = None,
) -> StageTransitionPlan:
    """Loss-capture entry point — writes the structured ``loss`` block + transitions to ``lost``.

    ``lost`` is a valid target from many substages per the TRANSITIONS
    table. This helper enforces "every loss has a reason" — direct
    transitions to ``lost`` via ``apply_transition`` are technically
    possible but the REST layer routes all loss through here.
    """
    when = now or datetime.now(UTC)
    canonical_reason = validate_reason(reason)
    resolved_lost_at_stage = lost_at_stage or lost_at_stage_for(deal.stage)

    plan = apply_transition(
        deal=deal,
        target_substage="lost",
        by_agent_id=by_agent_id,
        note=f"loss captured (reason={canonical_reason})",
        now=when,
    )

    # Splice the structured loss block in alongside stage_history.
    data = dict(deal.data or {})
    loss_block: dict[str, Any] = {
        "reason": canonical_reason,
        "lost_at_stage": resolved_lost_at_stage,
        "at": when.isoformat(),
        "by_agent_id": by_agent_id,
    }
    if competitor_brand:
        loss_block["competitor_brand"] = competitor_brand
    if notes:
        loss_block["notes"] = notes
    data["loss"] = loss_block
    deal.data = data
    # ``apply_transition`` already set is_terminal=True for ``lost``;
    # is_won remains False (only ``archived`` flips that on).
    return plan


__all__ = ("TERMINAL_SUBSTAGES", "WON_SUBSTAGE", "apply_transition", "record_loss")
