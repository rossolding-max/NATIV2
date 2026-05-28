"""Step 8 — dedupe + merge."""

from __future__ import annotations

from app.services.contact_enrichment import step_8_dedupe_merge
from app.services.contact_enrichment._models import EnrichedContact


def _c(
    *,
    contact_id: str,
    name: str,
    linkedin_url: str | None = None,
    email_address: str | None = None,
    title: str | None = None,
    seniority: str | None = None,
) -> EnrichedContact:
    return EnrichedContact(
        contact_id=contact_id,
        brand_id="gymshark",
        name=name,
        title=title,
        seniority=seniority,
        linkedin_url=linkedin_url,
        email_address=email_address,
        email_verification_status="verified" if email_address else None,
    )


def test_unit__step_8__no_duplicates_kept_as_is() -> None:
    out = step_8_dedupe_merge.run(
        contacts=[
            _c(contact_id="1", name="Alice", linkedin_url="https://l/1"),
            _c(contact_id="2", name="Bob", linkedin_url="https://l/2"),
        ]
    )
    assert len(out) == 2


def test_unit__step_8__merges_by_linkedin_url() -> None:
    out = step_8_dedupe_merge.run(
        contacts=[
            _c(contact_id="1", name="Alice", linkedin_url="https://l/a", title="VP Marketing"),
            _c(contact_id="2", name="Alice", linkedin_url="https://l/a", seniority="vp"),
        ]
    )
    assert len(out) == 1
    # Canonical row gets backfilled fields from the dup.
    assert out[0].title == "VP Marketing"
    assert out[0].seniority == "vp"


def test_unit__step_8__merges_by_name_and_email_domain() -> None:
    out = step_8_dedupe_merge.run(
        contacts=[
            _c(contact_id="1", name="Alice", email_address="alice@brand.com"),
            _c(contact_id="2", name="Alice", email_address="alice.x@brand.com"),
        ]
    )
    assert len(out) == 1  # same name + same email domain -> merged


def test_unit__step_8__merges_by_exact_email() -> None:
    out = step_8_dedupe_merge.run(
        contacts=[
            _c(contact_id="1", name="Alice", email_address="alice@brand.com"),
            _c(
                contact_id="2",
                name="Alice Smith",
                email_address="alice@brand.com",
                linkedin_url="https://l/a",
            ),
        ]
    )
    assert len(out) == 1
    # Second contact's linkedin_url backfills the canonical row.
    assert out[0].linkedin_url == "https://l/a"


def test_unit__step_8__linkedin_precedence_over_email() -> None:
    """Same LinkedIn URL wins over differing email — they're the same person."""
    out = step_8_dedupe_merge.run(
        contacts=[
            _c(
                contact_id="1",
                name="Alice",
                linkedin_url="https://l/a",
                email_address="a@brand.com",
            ),
            _c(
                contact_id="2",
                name="Alice",
                linkedin_url="https://l/a",
                email_address="alice@gmail.com",
            ),
        ]
    )
    assert len(out) == 1
    # Canonical email stays the first one (already present, not overwritten).
    assert out[0].email_address == "a@brand.com"


def test_unit__step_8__empty_input_returns_empty() -> None:
    assert step_8_dedupe_merge.run(contacts=[]) == []
