"""Unit tests for the GAP-08 contract template version bump."""

from __future__ import annotations

import pytest

from app.errors import ValidationError
from app.services import contract_template_setup as cts


@pytest.mark.parametrize(
    ("input_version", "expected"),
    [
        ("1.0.0", "1.0.1"),
        ("0.0.0", "0.0.1"),
        ("3.7.42", "3.7.43"),
        ("", "0.0.1"),
        ("2", "2.0.1"),
        ("2.4", "2.4.1"),
    ],
)
def test_unit__bump_patch(input_version: str, expected: str) -> None:
    assert cts._bump_patch(input_version) == expected  # pyright: ignore[reportPrivateUsage]


def test_unit__bump_patch__non_numeric__raises() -> None:
    with pytest.raises(ValidationError):
        cts._bump_patch("v1.2.3")  # pyright: ignore[reportPrivateUsage]


def test_unit__material_change__bumps_version() -> None:
    current = {
        "markdown_source": "old body",
        "template_version": "1.0.0",
        "default_governing_law": "California",
    }
    incoming = {"markdown_source": "new body"}
    merged = cts.materialise_contract_template_patch(current=current, incoming=incoming)
    assert merged["markdown_source"] == "new body"
    assert merged["template_version"] == "1.0.1"
    assert "template_updated_at" in merged


def test_unit__cosmetic_change__no_version_bump() -> None:
    current = {
        "markdown_source": "body",
        "template_version": "1.0.0",
        "template_updated_at": "2026-01-01T00:00:00+00:00",
        "legal_reviewer_id": "alice",
    }
    incoming = {"legal_reviewer_id": "bob"}
    merged = cts.materialise_contract_template_patch(current=current, incoming=incoming)
    assert merged["legal_reviewer_id"] == "bob"
    assert merged["template_version"] == "1.0.0"
    assert merged["template_updated_at"] == "2026-01-01T00:00:00+00:00"


def test_unit__client_supplied_version_ignored() -> None:
    current = {"markdown_source": "body", "template_version": "1.0.0"}
    incoming = {
        "markdown_source": "different body",
        "template_version": "99.99.99",  # ignored
        "template_updated_at": "2099-01-01T00:00:00+00:00",  # ignored
    }
    merged = cts.materialise_contract_template_patch(current=current, incoming=incoming)
    assert merged["template_version"] == "1.0.1"
    assert merged["template_updated_at"] != "2099-01-01T00:00:00+00:00"


@pytest.mark.parametrize(
    "field",
    [
        "markdown_source",
        "merge_field_definitions",
        "clause_applicability_rules",
        "narrative_placeholders",
        "default_governing_law",
        "default_jurisdiction",
    ],
)
def test_unit__every_material_field_triggers_bump(field: str) -> None:
    current = {field: "old", "template_version": "1.2.3"}
    if field in {
        "merge_field_definitions",
        "clause_applicability_rules",
        "narrative_placeholders",
    }:
        current[field] = []  # type: ignore[assignment]
        incoming = {field: [{"name": "x"}]}
    else:
        incoming = {field: "new"}
    merged = cts.materialise_contract_template_patch(current=current, incoming=incoming)
    assert merged["template_version"] == "1.2.4"


def test_unit__adopt_starter__returns_initial_template() -> None:
    template = cts.adopt_starter_template("management")
    assert template["based_on_starter_template_id"] == "management"
    assert "Talent Management Agreement" in template["markdown_source"]
    assert template["template_version"] == "0.1.0"


def test_unit__adopt_starter__unknown_slug__raises() -> None:
    with pytest.raises(ValidationError):
        cts.adopt_starter_template("nonexistent")


def test_unit__validate_completeness__declared_field__no_error() -> None:
    template = {
        "markdown_source": "Hi {{talent_name}} from {{agency_name}}!",
        "merge_field_definitions": [
            {"name": "talent_name"},
            {"name": "agency_name"},
        ],
    }
    assert cts.validate_template_completeness(template) == []


def test_unit__validate_completeness__undeclared_merge_field__error() -> None:
    template = {
        "markdown_source": "Hi {{talent_name}} from {{agency_name}}!",
        "merge_field_definitions": [{"name": "talent_name"}],
    }
    errors = cts.validate_template_completeness(template)
    assert any("agency_name" in e for e in errors)


def test_unit__validate_completeness__undeclared_clause__error() -> None:
    template = {
        "markdown_source": "{{#if exclusivity_clause}}This deal is exclusive.{{/if}}",
        "clause_applicability_rules": [],
    }
    errors = cts.validate_template_completeness(template)
    assert any("exclusivity_clause" in e for e in errors)
