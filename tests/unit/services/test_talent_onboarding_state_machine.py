"""Unit tests for the Phase 1 state-machine + activation cross-field guards."""

from __future__ import annotations

import pytest

from app.errors import BusinessRuleError, ValidationError
from app.services.talent_onboarding import (
    check_ready_for_activation,
    validate_data_against_schema,
    validate_status_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("onboarding", "active"),
        ("active", "archived"),
        ("active", "onboarding"),
        ("archived", "active"),
    ],
)
def test_unit__valid_status_transitions__no_raise(current: str, target: str) -> None:
    validate_status_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("onboarding", "archived"),
        ("archived", "onboarding"),
        ("onboarding", "draft"),  # unknown target
    ],
)
def test_unit__illegal_status_transitions__raise(current: str, target: str) -> None:
    with pytest.raises(BusinessRuleError):
        validate_status_transition(current, target)


def test_unit__same_status_transition__no_raise() -> None:
    validate_status_transition("active", "active")


def test_unit__check_ready__no_platforms__raises() -> None:
    with pytest.raises(BusinessRuleError, match="platforms"):
        check_ready_for_activation({})


def test_unit__check_ready__platform_without_scope_validated__raises() -> None:
    data = {"platforms": [{"platform": "instagram", "api_credentials": {}}]}
    with pytest.raises(BusinessRuleError, match="scope_validated_at"):
        check_ready_for_activation(data)


def test_unit__check_ready__brand_missing_industry__raises() -> None:
    data = {
        "platforms": [
            {
                "platform": "instagram",
                "api_credentials": {"scope_validated_at": "2026-01-01T00:00:00Z"},
            }
        ],
        "previous_brands": [{"brand": "Acme"}, {"brand": "Beta", "industry_id": "food"}],
        "billing_entity": {"legal_name": "Talent Co"},
    }
    with pytest.raises(BusinessRuleError, match="industry_id"):
        check_ready_for_activation(data)


def test_unit__check_ready__missing_billing_legal_name__raises() -> None:
    data = {
        "platforms": [
            {
                "platform": "instagram",
                "api_credentials": {"scope_validated_at": "2026-01-01T00:00:00Z"},
            }
        ],
    }
    with pytest.raises(BusinessRuleError, match=r"billing_entity\.legal_name"):
        check_ready_for_activation(data)


def test_unit__check_ready__all_green__no_raise() -> None:
    data = {
        "platforms": [
            {
                "platform": "instagram",
                "api_credentials": {"scope_validated_at": "2026-01-01T00:00:00Z"},
            }
        ],
        "previous_brands": [{"brand": "Acme", "industry_id": "consumer-electronics"}],
        "billing_entity": {"legal_name": "Talent Co", "country": "US"},
    }
    check_ready_for_activation(data)


def test_unit__validate_data__missing_required_field__raises() -> None:
    with pytest.raises(ValidationError):
        validate_data_against_schema({"id": "acme"})


def test_unit__validate_data__minimal_valid_passes() -> None:
    valid = {
        "id": "acme",
        "name": "Acme Talent",
        "platforms": [{"platform": "instagram", "handle": "@acme"}],
    }
    validate_data_against_schema(valid)
