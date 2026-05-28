"""Step 5 — strict email-verification honesty floor."""

from __future__ import annotations

from app.services.contact_enrichment import step_5_email_verify
from app.services.contact_enrichment._models import EnrichedContact


def _contact(*, email: str | None, status: str | None) -> EnrichedContact:
    return EnrichedContact(
        contact_id="bc_x",
        brand_id="gymshark",
        name="X",
        email_address=email,
        email_verification_status=status,
    )


def test_unit__step_5__verified_email_kept() -> None:
    contacts = step_5_email_verify.run(
        contacts=[_contact(email="x@example.com", status="verified")]
    )
    assert contacts[0].email_address == "x@example.com"
    assert contacts[0].email_verification_status == "verified"


def test_unit__step_5__catchall_email_kept() -> None:
    contacts = step_5_email_verify.run(
        contacts=[_contact(email="x@example.com", status="catchall")]
    )
    assert contacts[0].email_address == "x@example.com"


def test_unit__step_5__unverified_email_dropped() -> None:
    contacts = step_5_email_verify.run(
        contacts=[_contact(email="x@example.com", status="unverified")]
    )
    assert contacts[0].email_address is None
    assert contacts[0].email_verification_status == "unverified"


def test_unit__step_5__guessed_pattern_dropped() -> None:
    """Strict honesty floor — even guessed_pattern is rejected in v0.1."""
    contacts = step_5_email_verify.run(
        contacts=[_contact(email="guess@example.com", status="guessed_pattern")]
    )
    assert contacts[0].email_address is None


def test_unit__step_5__missing_status_dropped() -> None:
    """No status at all → drop."""
    contacts = step_5_email_verify.run(contacts=[_contact(email="x@example.com", status=None)])
    assert contacts[0].email_address is None
    assert contacts[0].email_verification_status == "unknown"


def test_unit__step_5__no_email_no_op() -> None:
    contacts = step_5_email_verify.run(contacts=[_contact(email=None, status=None)])
    assert contacts[0].email_address is None
    assert contacts[0].email_verification_status is None


def test_unit__step_5__status_case_insensitive() -> None:
    contacts = step_5_email_verify.run(
        contacts=[_contact(email="x@example.com", status="VERIFIED")]
    )
    assert contacts[0].email_address == "x@example.com"
