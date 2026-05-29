"""loss_reasons.validate_reason + lost_at_stage_for."""

from __future__ import annotations

import pytest

from app.services.deal_lifecycle.loss_reasons import (
    LOSS_REASONS,
    lost_at_stage_for,
    validate_reason,
)


def test_unit__loss__valid_reason_returns_canonical() -> None:
    assert validate_reason("budget") == "budget"
    assert validate_reason("BUDGET") == "budget"
    assert validate_reason("  competitor_won ") == "competitor_won"


def test_unit__loss__invalid_reason_raises() -> None:
    with pytest.raises(ValueError, match="invalid loss reason"):
        validate_reason("not_a_real_reason")


def test_unit__loss__lost_at_stage_resolves_known_stage() -> None:
    assert lost_at_stage_for("lead") == "lead"
    assert lost_at_stage_for("proposal") == "proposal"
    assert lost_at_stage_for("contract") == "contract"
    assert lost_at_stage_for("delivery") == "delivery"
    assert lost_at_stage_for("close") == "close"


def test_unit__loss__lost_at_stage_defaults_to_close_for_unknown_stage() -> None:
    assert lost_at_stage_for("invented") == "close"
    assert lost_at_stage_for("archived") == "close"


def test_unit__loss__enum_completeness() -> None:
    expected = {
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
    assert set(LOSS_REASONS) == expected
