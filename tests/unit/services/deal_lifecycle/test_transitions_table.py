"""Sanity-check the static TRANSITIONS table against the workflow doc.

If the table drifts from ``docs/deal_lifecycle_workflow.md`` (someone
edits one but not the other), these tests catch it.
"""

from __future__ import annotations

from app.services.deal_lifecycle.transitions import (
    AUTO_ADVANCE,
    STAGE_BY_SUBSTAGE,
    TERMINAL_SUBSTAGES,
    TRANSITIONS,
    WON_SUBSTAGE,
)

# All 28 substages in the schema enum.
_ALL_SUBSTAGES: frozenset[str] = frozenset(
    {
        "new_lead",
        "initial_call_scheduled",
        "initial_call_completed",
        "brief_received",
        "qualified",
        "disqualified",
        "proposal_drafting",
        "proposal_sent",
        "under_review",
        "negotiation",
        "terms_agreed",
        "contract_drafting",
        "contract_in_review_brand",
        "contract_in_review_talent",
        "contract_revisions",
        "contract_executed",
        "contract_failed",
        "pre_production",
        "content_in_production",
        "pending_brand_approval",
        "revisions_requested",
        "approved_for_posting",
        "live",
        "performance_window",
        "invoice_sent",
        "invoice_paid",
        "post_campaign_reporting",
        "archived",
        "lost",
        "killed",
        "paused",
    }
)


def test_unit__transitions__every_substage_in_table() -> None:
    # ``paused`` doesn't have explicit outbound edges in the table (the
    # orchestrator resumes via the prior substage); all others must.
    expected = _ALL_SUBSTAGES - {"paused"}
    assert set(TRANSITIONS.keys()) == expected


def test_unit__transitions__terminal_substages_have_no_outbound_edges() -> None:
    for substage in TERMINAL_SUBSTAGES:
        assert TRANSITIONS.get(substage, frozenset()) == frozenset()


def test_unit__transitions__won_substage_is_archived() -> None:
    assert WON_SUBSTAGE == "archived"
    assert "archived" in TERMINAL_SUBSTAGES


def test_unit__transitions__auto_advance_targets_are_in_transitions() -> None:
    for trigger, follow_on in AUTO_ADVANCE.items():
        assert trigger in TRANSITIONS
        assert follow_on in TRANSITIONS.get(trigger, frozenset()), (
            f"auto-advance {trigger}->{follow_on} not in TRANSITIONS[{trigger}]"
        )


def test_unit__transitions__every_outbound_target_is_known() -> None:
    """No transition points to a substage that isn't in the schema enum."""
    for substage, targets in TRANSITIONS.items():
        for target in targets:
            assert target in _ALL_SUBSTAGES, f"{substage}->{target} references unknown substage"


def test_unit__transitions__stage_by_substage_covers_persistent_substages() -> None:
    """Persistent substages (not lost/killed/paused) have stable stage tags."""
    stage_agnostic = {"lost", "killed", "paused"}
    for substage in _ALL_SUBSTAGES - stage_agnostic:
        assert substage in STAGE_BY_SUBSTAGE, f"{substage} missing from STAGE_BY_SUBSTAGE"
        assert STAGE_BY_SUBSTAGE[substage] in {
            "lead",
            "proposal",
            "contract",
            "delivery",
            "close",
            "archived",
        }
