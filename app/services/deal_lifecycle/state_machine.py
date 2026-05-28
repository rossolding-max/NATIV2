"""Validate one deal-state transition + chain auto-advance follow-ons.

Pure functions only — no DB, no side effects. The orchestrator handles
persistence + ``stage_history[]`` append.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.errors import BusinessRuleError
from app.services.deal_lifecycle.transitions import (
    AUTO_ADVANCE,
    STAGE_BY_SUBSTAGE,
    TERMINAL_SUBSTAGES,
    TRANSITIONS,
    WON_SUBSTAGE,
)


@dataclass(frozen=True)
class StageTransitionStep:
    """One step in a transition chain.

    ``by_agent_id`` is the requesting agent for the FIRST step; the
    auto-advance step gets ``"system"`` so the audit trail is honest
    about who drove which row.
    """

    stage: str
    substage: str
    by_agent_id: str
    note: str | None
    is_auto_advance: bool


@dataclass(frozen=True)
class StageTransitionPlan:
    """Result of ``transition()`` — 1 or 2 ordered steps."""

    steps: tuple[StageTransitionStep, ...]
    final_is_terminal: bool
    final_is_won: bool


def _resolve_stage(*, target_substage: str, current_stage: str) -> str:
    """Stage to use for ``target_substage`` given the deal's current stage.

    Stage-agnostic substages (``lost``, ``killed``, ``paused``) keep
    the current stage so an enquiry "where was this deal lost?" can
    inspect ``deal.stage`` directly.
    """
    explicit = STAGE_BY_SUBSTAGE.get(target_substage)
    if explicit is not None:
        return explicit
    return current_stage


def transition(
    *,
    current_stage: str,
    current_substage: str,
    target_substage: str,
    by_agent_id: str,
    note: str | None = None,
) -> StageTransitionPlan:
    """Build the chain to apply for one transition.

    Raises ``BusinessRuleError`` when the target isn't in the current
    substage's allowed set. The chain length is 1 normally; 2 when the
    target triggers an auto-advance (e.g. ``qualified`` chains to
    ``proposal_drafting``).
    """
    allowed = TRANSITIONS.get(current_substage)
    if allowed is None:
        raise BusinessRuleError(
            f"unknown current substage {current_substage!r}",
            detail={"current_substage": current_substage},
        )
    if target_substage not in allowed:
        raise BusinessRuleError(
            f"transition {current_substage!r} -> {target_substage!r} not allowed",
            detail={
                "from_substage": current_substage,
                "to_substage": target_substage,
                "allowed_targets": sorted(allowed),
            },
        )

    first = StageTransitionStep(
        stage=_resolve_stage(target_substage=target_substage, current_stage=current_stage),
        substage=target_substage,
        by_agent_id=by_agent_id,
        note=note,
        is_auto_advance=False,
    )

    steps: list[StageTransitionStep] = [first]

    follow_on = AUTO_ADVANCE.get(target_substage)
    if follow_on is not None:
        # Recursively validate the auto-advance link — should always be
        # in the transitions table (defensive belt-and-braces).
        follow_on_allowed = TRANSITIONS.get(target_substage) or frozenset()
        if follow_on not in follow_on_allowed:
            raise BusinessRuleError(
                f"auto-advance {target_substage!r} -> {follow_on!r} not in TRANSITIONS",
                detail={"from_substage": target_substage, "to_substage": follow_on},
            )
        steps.append(
            StageTransitionStep(
                stage=_resolve_stage(target_substage=follow_on, current_stage=first.stage),
                substage=follow_on,
                by_agent_id="system",
                note=f"auto-advance from {target_substage}",
                is_auto_advance=True,
            )
        )

    final = steps[-1]
    return StageTransitionPlan(
        steps=tuple(steps),
        final_is_terminal=final.substage in TERMINAL_SUBSTAGES,
        final_is_won=final.substage == WON_SUBSTAGE,
    )
