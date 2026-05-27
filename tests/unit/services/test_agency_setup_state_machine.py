"""Unit tests for the Phase 0 state-machine transitions + cross-field guards."""

from __future__ import annotations

import pytest

from app.errors import BusinessRuleError, ValidationError
from app.services.agency_setup import (
    check_ready_for_activation,
    validate_data_against_schema,
    validate_status_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("setup_in_progress", "awaiting_dns"),
        ("awaiting_dns", "warming_up"),
        ("warming_up", "active"),
        ("warming_up", "awaiting_dns"),
        ("active", "warming_up"),
        ("awaiting_dns", "setup_in_progress"),
    ],
)
def test_unit__valid_status_transitions__no_raise(current: str, target: str) -> None:
    validate_status_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("setup_in_progress", "active"),
        ("setup_in_progress", "warming_up"),
        ("awaiting_dns", "active"),
    ],
)
def test_unit__illegal_status_transitions__raise(current: str, target: str) -> None:
    with pytest.raises(BusinessRuleError):
        validate_status_transition(current, target)


def test_unit__same_status_transition__no_raise() -> None:
    validate_status_transition("active", "active")


def test_unit__unknown_status__raises() -> None:
    with pytest.raises(BusinessRuleError):
        validate_status_transition("alien", "active")


def test_unit__check_ready__missing_mailbox__raises() -> None:
    with pytest.raises(BusinessRuleError):
        check_ready_for_activation({"sending_mailboxes": []})


def test_unit__check_ready__dns_unverified__raises() -> None:
    data = {"sending_mailboxes": [{"dns_records_verified": False, "warmup_status": "complete"}]}
    with pytest.raises(BusinessRuleError, match="DNS"):
        check_ready_for_activation(data)


def test_unit__check_ready__warmup_incomplete__raises() -> None:
    data = {"sending_mailboxes": [{"dns_records_verified": True, "warmup_status": "in_progress"}]}
    with pytest.raises(BusinessRuleError, match="warmup"):
        check_ready_for_activation(data)


def test_unit__check_ready__all_green__no_raise() -> None:
    data = {"sending_mailboxes": [{"dns_records_verified": True, "warmup_status": "complete"}]}
    check_ready_for_activation(data)


def test_unit__validate_data__missing_required_field__raises() -> None:
    with pytest.raises(ValidationError):
        validate_data_against_schema({"agency_id": "acme"})


def test_unit__validate_data__minimal_valid__no_raise() -> None:
    valid = {
        "agency_id": "acme",
        "name": "Acme",
        "domain": "acme.com",
        "company_address": "1 Main St",
        "agents": [
            {
                "agent_id": "sarah",
                "name": "Sarah",
                "email": "sarah@acme.com",
                "is_primary": True,
                "represents_talent_ids": [],
            }
        ],
        "sending_mailboxes": [
            {
                "email": "sarah@acme.com",
                "agent_id": "sarah",
                "purpose": "named_agent_outreach",
                "warmup_status": "pending",
            }
        ],
        "default_signature_template": (
            "Sarah from {agent_name} | {agency_address}\nUnsubscribe: {unsubscribe_link}"
        ),
    }
    validate_data_against_schema(valid)
