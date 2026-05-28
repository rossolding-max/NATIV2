"""Static state-machine tables for the Phase 4 deal lifecycle.

Mirrors the transition table in ``docs/deal_lifecycle_workflow.md`` verbatim.
Every documented transition is in ``TRANSITIONS``; any pair NOT in the
allowed set is rejected by ``state_machine.transition``.

The three auto-cross-stage transitions per the M10 locked decision:
- ``qualified`` -> ``proposal_drafting``
- ``terms_agreed`` -> ``contract_drafting``
- ``contract_executed`` -> ``pre_production``

These are encoded in ``AUTO_ADVANCE`` so the orchestrator can chain
them in a single ``POST /transition`` call and write both audit entries.
"""

from __future__ import annotations

# substage -> set of allowed next substages.
TRANSITIONS: dict[str, frozenset[str]] = {
    # ── LEAD ─────────────────────────────────────────────────────────
    "new_lead": frozenset({"initial_call_scheduled", "disqualified", "lost", "paused"}),
    "initial_call_scheduled": frozenset(
        {"initial_call_completed", "disqualified", "lost", "paused"}
    ),
    "initial_call_completed": frozenset({"brief_received", "qualified", "disqualified", "paused"}),
    "brief_received": frozenset({"qualified", "disqualified", "paused"}),
    "qualified": frozenset({"proposal_drafting"}),
    # ── PROPOSAL ─────────────────────────────────────────────────────
    "proposal_drafting": frozenset({"proposal_sent", "lost", "paused"}),
    "proposal_sent": frozenset({"under_review", "negotiation", "terms_agreed", "lost", "paused"}),
    "under_review": frozenset({"negotiation", "terms_agreed", "lost", "paused"}),
    "negotiation": frozenset({"terms_agreed", "proposal_sent", "lost", "paused"}),
    "terms_agreed": frozenset({"contract_drafting"}),
    # ── CONTRACT ─────────────────────────────────────────────────────
    "contract_drafting": frozenset(
        {
            "contract_in_review_brand",
            "contract_in_review_talent",
            "contract_failed",
            "lost",
        }
    ),
    "contract_in_review_brand": frozenset(
        {
            "contract_in_review_talent",
            "contract_revisions",
            "contract_executed",
            "contract_failed",
        }
    ),
    "contract_in_review_talent": frozenset(
        {
            "contract_in_review_brand",
            "contract_revisions",
            "contract_executed",
            "contract_failed",
        }
    ),
    "contract_revisions": frozenset(
        {
            "contract_in_review_brand",
            "contract_in_review_talent",
            "contract_failed",
        }
    ),
    "contract_executed": frozenset({"pre_production"}),
    # ── DELIVERY ─────────────────────────────────────────────────────
    "pre_production": frozenset({"content_in_production", "killed", "paused"}),
    "content_in_production": frozenset({"pending_brand_approval", "killed", "paused"}),
    "pending_brand_approval": frozenset({"revisions_requested", "approved_for_posting", "killed"}),
    "revisions_requested": frozenset({"content_in_production", "pending_brand_approval", "killed"}),
    "approved_for_posting": frozenset({"live"}),
    "live": frozenset({"performance_window"}),
    "performance_window": frozenset({"invoice_sent"}),
    # ── CLOSE ────────────────────────────────────────────────────────
    "invoice_sent": frozenset({"invoice_paid", "paused"}),
    "invoice_paid": frozenset({"post_campaign_reporting"}),
    "post_campaign_reporting": frozenset({"archived"}),
    # ── Terminal / paused (no outbound) ──────────────────────────────
    "disqualified": frozenset(),
    "lost": frozenset(),
    "killed": frozenset(),
    "contract_failed": frozenset(),
    "archived": frozenset(),
}

# Substages with no outbound edges. ``is_terminal`` flips to True on
# arrival at any of these.
TERMINAL_SUBSTAGES: frozenset[str] = frozenset(
    {"disqualified", "lost", "killed", "contract_failed", "archived"}
)

# The single won-terminal substage. ``is_won`` flips True only here.
WON_SUBSTAGE: str = "archived"

# Auto-cross-stage chains. When an agent transitions to the key, the
# orchestrator ALSO transitions to the value (writing both audit
# entries) so the agent doesn't need to click twice.
AUTO_ADVANCE: dict[str, str] = {
    "qualified": "proposal_drafting",
    "terms_agreed": "contract_drafting",
    "contract_executed": "pre_production",
}

# substage -> stage map derived from the schema's stage groupings.
_LEAD = {
    "new_lead",
    "initial_call_scheduled",
    "initial_call_completed",
    "brief_received",
    "qualified",
    "disqualified",
}
_PROPOSAL = {
    "proposal_drafting",
    "proposal_sent",
    "under_review",
    "negotiation",
    "terms_agreed",
}
_CONTRACT = {
    "contract_drafting",
    "contract_in_review_brand",
    "contract_in_review_talent",
    "contract_revisions",
    "contract_executed",
    "contract_failed",
}
_DELIVERY = {
    "pre_production",
    "content_in_production",
    "pending_brand_approval",
    "revisions_requested",
    "approved_for_posting",
    "live",
    "performance_window",
}
_CLOSE = {"invoice_sent", "invoice_paid", "post_campaign_reporting"}
_ARCHIVED = {"archived"}

# ``lost``, ``killed``, and ``paused`` retain the stage they arrived
# in (orchestrator resolves stage from the deal's *current* stage when
# transitioning to one of these). They appear in EVERY mapping but
# carry a sentinel value.
STAGE_BY_SUBSTAGE: dict[str, str] = (
    {s: "lead" for s in _LEAD}
    | {s: "proposal" for s in _PROPOSAL}
    | {s: "contract" for s in _CONTRACT}
    | {s: "delivery" for s in _DELIVERY}
    | {s: "close" for s in _CLOSE}
    | {s: "archived" for s in _ARCHIVED}
    # ``lost`` / ``killed`` / ``paused`` aren't in the per-stage sets —
    # the orchestrator preserves the prior stage when transitioning
    # to them (they're "decorations" on whatever stage the deal was in).
)


# Reverse lookup: every substage -> "stage anchor" for loss tagging.
def stage_for_substage(substage: str) -> str | None:
    """Return the stage owning this substage, or None for stage-agnostic ones."""
    return STAGE_BY_SUBSTAGE.get(substage)
