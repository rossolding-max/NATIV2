"""Unit tests for the M6 KPI honesty-floor validator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.errors import ValidationError
from app.services.kpi_validation import (
    flag_suspicious_values,
    validate_deal_against_schema,
    validate_deal_kpis,
    validate_deal_payload,
    validate_kpi_metric,
)

_TODAY = datetime.now(UTC).date().isoformat()


# ── validate_kpi_metric ───────────────────────────────────────────────


def test_unit__valid_metric_returns_no_errors() -> None:
    errors = validate_kpi_metric(
        "reach",
        {"value": 1_240_000, "source": "platform_verified", "as_of": _TODAY},
    )
    assert errors == []


def test_unit__missing_value_is_rejected() -> None:
    errors = validate_kpi_metric("reach", {"source": "platform_verified", "as_of": _TODAY})
    assert any("'value'" in e for e in errors)


def test_unit__missing_source_is_rejected() -> None:
    errors = validate_kpi_metric("reach", {"value": 100, "as_of": _TODAY})
    assert any("'source'" in e for e in errors)


def test_unit__invalid_source_is_rejected() -> None:
    errors = validate_kpi_metric("reach", {"value": 100, "source": "made-it-up", "as_of": _TODAY})
    assert any("must be one of" in e for e in errors)


def test_unit__missing_as_of_is_rejected_per_honesty_floor() -> None:
    """as_of is REQUIRED by M6 honesty floor (stricter than the shared schema)."""
    errors = validate_kpi_metric("reach", {"value": 100, "source": "platform_verified"})
    assert any("'as_of'" in e for e in errors)


def test_unit__future_as_of_is_rejected() -> None:
    future = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    errors = validate_kpi_metric(
        "reach", {"value": 100, "source": "platform_verified", "as_of": future}
    )
    assert any("future" in e for e in errors)


def test_unit__negative_value_is_rejected() -> None:
    errors = validate_kpi_metric(
        "reach", {"value": -1, "source": "platform_verified", "as_of": _TODAY}
    )
    assert any(">= 0" in e for e in errors)


# ── flag_suspicious_values (non-blocking) ─────────────────────────────


def test_unit__engagement_rate_over_100_is_flagged() -> None:
    flags = flag_suspicious_values(
        "engagement_rate_pct",
        {"value": 105, "source": "platform_verified", "as_of": _TODAY},
    )
    assert flags  # at least one flag


def test_unit__plausible_engagement_rate_is_not_flagged() -> None:
    flags = flag_suspicious_values(
        "engagement_rate_pct",
        {"value": 4.2, "source": "platform_verified", "as_of": _TODAY},
    )
    assert flags == []


# ── validate_deal_kpis (aggregate) ────────────────────────────────────


def test_unit__valid_kpis_block_returns_no_errors() -> None:
    kpis = {
        "reach": {"value": 1_000_000, "source": "platform_verified", "as_of": _TODAY},
        "impressions": {"value": 2_500_000, "source": "platform_verified", "as_of": _TODAY},
    }
    assert validate_deal_kpis(kpis) == []


def test_unit__partial_metric_in_block_is_rejected() -> None:
    """A metric with value but no source / as_of fails the honesty floor."""
    kpis = {
        "reach": {"value": 1_000_000, "source": "platform_verified", "as_of": _TODAY},
        "impressions": {"value": 2_500_000},  # missing source + as_of
    }
    errors = validate_deal_kpis(kpis)
    assert any("impressions" in e for e in errors)


def test_unit__omitted_metric_is_legal_absence() -> None:
    """Whole-key omission is fine — the honesty floor only applies to populated metrics."""
    kpis = {
        "reach": {"value": 1_000_000, "source": "platform_verified", "as_of": _TODAY},
        # impressions intentionally absent
    }
    assert validate_deal_kpis(kpis) == []


# ── validate_deal_against_schema ──────────────────────────────────────


def _make_minimal_deal() -> dict:
    return {
        "deal_id": "deal_2025_acme_abc123",
        "brand_id": "acme",
        "industry_id": "consumer-electronics",
        "campaign_type": "sponsored_post",
        "outcome": "successful",
        "first_recorded_at": "2026-01-01T00:00:00Z",
        "last_updated_at": "2026-01-01T00:00:00Z",
    }


def test_unit__minimal_deal_passes_schema() -> None:
    validate_deal_against_schema(_make_minimal_deal())  # no raise


def test_unit__missing_required_field_raises() -> None:
    deal = _make_minimal_deal()
    del deal["outcome"]
    with pytest.raises(ValidationError, match="invalid"):
        validate_deal_against_schema(deal)


def test_unit__invalid_outcome_enum_raises() -> None:
    deal = _make_minimal_deal()
    deal["outcome"] = "made-up-outcome"
    with pytest.raises(ValidationError):
        validate_deal_against_schema(deal)


# ── validate_deal_payload (composite) ─────────────────────────────────


def test_unit__honesty_floor_kpis_in_payload_raise() -> None:
    """Schema-valid metric (value + source) but missing as_of fails honesty floor."""
    deal = _make_minimal_deal()
    deal["kpis"] = {"reach": {"value": 100, "source": "platform_verified"}}  # missing as_of
    with pytest.raises(ValidationError, match="honesty floor"):
        validate_deal_payload(deal)


def test_unit__valid_payload_returns_suspicion_flags_only() -> None:
    """A valid payload with one suspicious-but-allowed value returns flags + no raise."""
    deal = _make_minimal_deal()
    deal["kpis"] = {
        "reach": {"value": 1_000_000, "source": "platform_verified", "as_of": _TODAY},
        "engagement_rate_pct": {
            "value": 35,  # unusually high — suspicious but allowed
            "source": "platform_verified",
            "as_of": _TODAY,
        },
    }
    flags = validate_deal_payload(deal)
    assert any("engagement_rate_pct" in f for f in flags)
