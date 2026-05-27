"""Unit tests for ``materialise_invoice_template_patch`` (GAP-07)."""

from __future__ import annotations

import pytest

from app.errors import ValidationError
from app.services import invoice_template as invtpl
from app.services.invoice_template import materialise_invoice_template_patch


def _bump_patch(version: str) -> str:
    return invtpl._bump_patch(version)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ("input_version", "expected"),
    [
        ("1.0.0", "1.0.1"),
        ("0.9.7", "0.9.8"),
        ("2.4.99", "2.4.100"),
        ("", "0.0.1"),
        ("1", "1.0.1"),
        ("1.2", "1.2.1"),
    ],
)
def test_unit__bump_patch(input_version: str, expected: str) -> None:
    assert _bump_patch(input_version) == expected


def test_unit__bump_patch__non_numeric__raises() -> None:
    with pytest.raises(ValidationError):
        _bump_patch("v1.2.3")


def test_unit__material_change__bumps_version() -> None:
    current = {
        "markdown_source": "old",
        "template_version": "1.0.0",
        "tax_handling": "vat_added",
    }
    incoming = {"markdown_source": "new content"}
    merged = materialise_invoice_template_patch(current=current, incoming=incoming)
    assert merged["markdown_source"] == "new content"
    assert merged["template_version"] == "1.0.1"
    assert "template_updated_at" in merged


def test_unit__cosmetic_change__no_bump() -> None:
    current = {
        "markdown_source": "body",
        "template_version": "1.0.0",
        "template_updated_at": "2026-01-01T00:00:00+00:00",
        "invoice_number_prefix": "INV-",
    }
    incoming = {"invoice_number_prefix": "ACME-"}
    merged = materialise_invoice_template_patch(current=current, incoming=incoming)
    assert merged["invoice_number_prefix"] == "ACME-"
    assert merged["template_version"] == "1.0.0"  # unchanged
    assert merged["template_updated_at"] == "2026-01-01T00:00:00+00:00"


def test_unit__client_supplied_version__ignored() -> None:
    """Server is authoritative on template_version + template_updated_at."""
    current = {"markdown_source": "body", "template_version": "1.0.0"}
    incoming = {
        "markdown_source": "different body",
        "template_version": "99.99.99",  # ignored
        "template_updated_at": "2099-01-01T00:00:00+00:00",  # ignored
    }
    merged = materialise_invoice_template_patch(current=current, incoming=incoming)
    assert merged["template_version"] == "1.0.1"
    # The server set a fresh timestamp; the client's was ignored.
    assert merged["template_updated_at"] != "2099-01-01T00:00:00+00:00"


def test_unit__first_write__seeds_version() -> None:
    current: dict[str, object] = {}
    incoming = {"markdown_source": "fresh template"}
    merged = materialise_invoice_template_patch(current=current, incoming=incoming)
    assert merged["template_version"] == "0.0.1"
    assert "template_updated_at" in merged


def test_unit__no_change_to_material__retains_version() -> None:
    current = {
        "markdown_source": "body",
        "tax_handling": "none",
        "template_version": "1.0.5",
        "template_updated_at": "2026-01-01T00:00:00+00:00",
    }
    # Re-submit the same material body — should not bump.
    incoming = {"markdown_source": "body", "tax_handling": "none"}
    merged = materialise_invoice_template_patch(current=current, incoming=incoming)
    assert merged["template_version"] == "1.0.5"


@pytest.mark.parametrize(
    "field",
    [
        "markdown_source",
        "tax_handling",
        "invoice_footer",
        "payment_instructions_markdown",
        "default_payment_terms_days",
    ],
)
def test_unit__every_material_field_triggers_bump(field: str) -> None:
    current = {field: "old", "template_version": "1.2.3"}
    if field == "default_payment_terms_days":
        current[field] = 30  # type: ignore[assignment]
        incoming = {field: 45}
    else:
        incoming = {field: "new"}
    merged = materialise_invoice_template_patch(current=current, incoming=incoming)
    assert merged["template_version"] == "1.2.4"
