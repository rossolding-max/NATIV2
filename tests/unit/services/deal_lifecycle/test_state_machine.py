"""state_machine.transition — valid vs invalid + auto-advance chains."""

from __future__ import annotations

import pytest

from app.errors import BusinessRuleError
from app.services.deal_lifecycle.state_machine import transition


def test_unit__sm__valid_simple_transition_returns_one_step() -> None:
    plan = transition(
        current_stage="lead",
        current_substage="new_lead",
        target_substage="initial_call_scheduled",
        by_agent_id="agent_alice",
    )
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.stage == "lead"
    assert step.substage == "initial_call_scheduled"
    assert step.by_agent_id == "agent_alice"
    assert step.is_auto_advance is False
    assert plan.final_is_terminal is False
    assert plan.final_is_won is False


def test_unit__sm__qualified_auto_advances_to_proposal_drafting() -> None:
    plan = transition(
        current_stage="lead",
        current_substage="initial_call_completed",
        target_substage="qualified",
        by_agent_id="agent_alice",
    )
    assert len(plan.steps) == 2
    first, second = plan.steps
    assert first.stage == "lead"
    assert first.substage == "qualified"
    assert first.is_auto_advance is False
    assert first.by_agent_id == "agent_alice"

    assert second.stage == "proposal"
    assert second.substage == "proposal_drafting"
    assert second.is_auto_advance is True
    assert second.by_agent_id == "system"

    assert plan.final_is_terminal is False


def test_unit__sm__terms_agreed_auto_advances_to_contract_drafting() -> None:
    plan = transition(
        current_stage="proposal",
        current_substage="negotiation",
        target_substage="terms_agreed",
        by_agent_id="agent_alice",
    )
    assert len(plan.steps) == 2
    assert plan.steps[-1].stage == "contract"
    assert plan.steps[-1].substage == "contract_drafting"


def test_unit__sm__contract_executed_auto_advances_to_pre_production() -> None:
    plan = transition(
        current_stage="contract",
        current_substage="contract_in_review_brand",
        target_substage="contract_executed",
        by_agent_id="agent_alice",
    )
    assert len(plan.steps) == 2
    assert plan.steps[-1].stage == "delivery"
    assert plan.steps[-1].substage == "pre_production"


def test_unit__sm__invalid_transition_raises() -> None:
    with pytest.raises(BusinessRuleError) as exc:
        transition(
            current_stage="lead",
            current_substage="new_lead",
            target_substage="contract_drafting",  # not in allowed set
            by_agent_id="agent_alice",
        )
    assert "not allowed" in str(exc.value)
    assert exc.value.detail is not None
    assert exc.value.detail.get("from_substage") == "new_lead"


def test_unit__sm__terminal_substage_is_terminal_flag() -> None:
    plan = transition(
        current_stage="lead",
        current_substage="initial_call_completed",
        target_substage="disqualified",
        by_agent_id="agent_alice",
    )
    assert plan.final_is_terminal is True
    assert plan.final_is_won is False


def test_unit__sm__archived_is_won_flag() -> None:
    plan = transition(
        current_stage="close",
        current_substage="post_campaign_reporting",
        target_substage="archived",
        by_agent_id="system",
    )
    assert plan.final_is_terminal is True
    assert plan.final_is_won is True


def test_unit__sm__paused_keeps_current_stage() -> None:
    """``paused`` is stage-agnostic — should preserve the deal's current stage."""
    plan = transition(
        current_stage="proposal",
        current_substage="proposal_sent",
        target_substage="paused",
        by_agent_id="agent_alice",
    )
    assert plan.steps[0].stage == "proposal"
    assert plan.steps[0].substage == "paused"


def test_unit__sm__lost_keeps_current_stage() -> None:
    """``lost`` is stage-agnostic and should preserve the deal's current stage."""
    plan = transition(
        current_stage="proposal",
        current_substage="negotiation",  # ``negotiation`` allows → lost
        target_substage="lost",
        by_agent_id="agent_alice",
    )
    assert plan.steps[0].stage == "proposal"
    assert plan.final_is_terminal is True


def test_unit__sm__unknown_current_substage_raises() -> None:
    with pytest.raises(BusinessRuleError, match="unknown current substage"):
        transition(
            current_stage="lead",
            current_substage="invented_state",
            target_substage="new_lead",
            by_agent_id="x",
        )
