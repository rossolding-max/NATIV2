"""Orchestrator — applies a transition + appends audit + syncs scalar columns."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.services.deal_lifecycle import orchestrator


def _deal(stage: str = "lead", substage: str = "new_lead") -> MagicMock:
    d = MagicMock()
    d.stage = stage
    d.substage = substage
    d.is_terminal = False
    d.is_won = False
    d.data = {}
    return d


def test_unit__orch__apply_transition_writes_one_history_entry() -> None:
    deal = _deal()
    plan = orchestrator.apply_transition(
        deal=deal,
        target_substage="initial_call_scheduled",
        by_agent_id="agent_alice",
    )
    assert deal.substage == "initial_call_scheduled"
    assert deal.stage == "lead"
    history = deal.data["stage_history"]
    assert len(history) == 1
    assert history[0]["substage"] == "initial_call_scheduled"
    assert history[0]["by_agent_id"] == "agent_alice"
    assert plan.steps[0].substage == "initial_call_scheduled"


def test_unit__orch__auto_advance_writes_two_history_entries() -> None:
    deal = _deal(stage="lead", substage="initial_call_completed")
    orchestrator.apply_transition(
        deal=deal,
        target_substage="qualified",
        by_agent_id="agent_alice",
    )
    # Final state after auto-advance.
    assert deal.stage == "proposal"
    assert deal.substage == "proposal_drafting"
    history = deal.data["stage_history"]
    assert len(history) == 2
    assert history[0]["substage"] == "qualified"
    assert history[0]["by_agent_id"] == "agent_alice"
    assert history[1]["substage"] == "proposal_drafting"
    assert history[1]["by_agent_id"] == "system"
    assert "auto-advance" in (history[1].get("note") or "")


def test_unit__orch__terminal_transition_sets_is_terminal() -> None:
    deal = _deal(stage="lead", substage="brief_received")
    orchestrator.apply_transition(
        deal=deal, target_substage="disqualified", by_agent_id="agent_alice"
    )
    assert deal.is_terminal is True
    assert deal.is_won is False


def test_unit__orch__archived_sets_is_won() -> None:
    deal = _deal(stage="close", substage="post_campaign_reporting")
    orchestrator.apply_transition(deal=deal, target_substage="archived", by_agent_id="system")
    assert deal.stage == "archived"
    assert deal.is_terminal is True
    assert deal.is_won is True


def test_unit__orch__preserves_existing_data_blocks() -> None:
    deal = _deal()
    deal.data = {"user_notes": "x", "lead": {"brief_text": "yo"}}
    orchestrator.apply_transition(
        deal=deal,
        target_substage="initial_call_scheduled",
        by_agent_id="agent_alice",
    )
    assert deal.data["user_notes"] == "x"
    assert deal.data["lead"]["brief_text"] == "yo"
    assert "stage_history" in deal.data


def test_unit__orch__record_loss_writes_structured_block_plus_transition() -> None:
    deal = _deal(stage="proposal", substage="negotiation")
    plan = orchestrator.record_loss(
        deal=deal,
        reason="budget",
        by_agent_id="agent_alice",
        competitor_brand="Gymshark",
        notes="out of FY budget",
    )
    assert deal.substage == "lost"
    assert deal.is_terminal is True
    assert deal.is_won is False
    loss = deal.data["loss"]
    assert loss["reason"] == "budget"
    assert loss["lost_at_stage"] == "proposal"
    assert loss["competitor_brand"] == "Gymshark"
    assert loss["notes"] == "out of FY budget"
    assert loss["by_agent_id"] == "agent_alice"
    # The transition + the loss entry both land in history.
    assert any(h["substage"] == "lost" for h in deal.data["stage_history"])
    assert len(plan.steps) == 1


def test_unit__orch__record_loss_with_explicit_lost_at_stage() -> None:
    """Explicit lost_at_stage overrides the auto-resolved one."""
    deal = _deal(stage="proposal", substage="proposal_sent")  # allows → lost
    orchestrator.record_loss(
        deal=deal,
        reason="timing",
        by_agent_id="agent_alice",
        lost_at_stage="contract",  # explicit override (e.g. we lost it later in flight)
    )
    assert deal.data["loss"]["lost_at_stage"] == "contract"


def test_unit__orch__transition_uses_supplied_clock() -> None:
    deal = _deal()
    pinned = datetime(2026, 5, 28, 16, 0, tzinfo=UTC)
    orchestrator.apply_transition(
        deal=deal,
        target_substage="initial_call_scheduled",
        by_agent_id="agent_alice",
        now=pinned,
    )
    assert deal.data["stage_history"][0]["at"] == pinned.isoformat()


def test_unit__orch__note_persists_to_audit_entry() -> None:
    deal = _deal()
    orchestrator.apply_transition(
        deal=deal,
        target_substage="initial_call_scheduled",
        by_agent_id="agent_alice",
        note="kicked off via inbound call",
    )
    assert deal.data["stage_history"][0]["note"] == "kicked off via inbound call"
