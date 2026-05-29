"""Loss-reason enum + ``lost_at_stage`` resolution.

The structured loss block lives at ``deal.data.loss`` per
``schemas/deal.schema.json``. Every PROPOSAL / CONTRACT / late-LEAD loss
must capture a reason from this enum + the stage where the deal was
lost (for analytics: "we lose 60% of contract-stage deals to terms
disagreements; that's where we coach harder").
"""

from __future__ import annotations

from typing import Final

# Same enum as the Pydantic codegen at ``deal_schema.Reason``. Re-export
# as plain strings so callers (including the REST body validator) can
# use them without pulling in the heavier codegen module.
LOSS_REASONS: Final[frozenset[str]] = frozenset(
    {
        "budget",
        "timing",
        "competitor_won",
        "internal_pivot",
        "talent_no_fit",
        "terms_disagreed",
        "unresponsive",
        "compliance_block",
        "other",
    }
)


def lost_at_stage_for(current_stage: str) -> str:
    """Resolve the stage tag captured on a loss given the deal's stage."""
    # The valid lost_at_stage values per the schema are the 5 non-archived
    # stages. ``archived`` shouldn't lose (deals only reach archive via
    # the won path), but we fall back to "close" defensively.
    if current_stage in {"lead", "proposal", "contract", "delivery", "close"}:
        return current_stage
    return "close"


def validate_reason(reason: str) -> str:
    """Return the lowercased reason if valid; raise ValueError otherwise."""
    lowered = (reason or "").strip().lower()
    if lowered not in LOSS_REASONS:
        raise ValueError(f"invalid loss reason {reason!r}; allowed: {sorted(LOSS_REASONS)}")
    return lowered
