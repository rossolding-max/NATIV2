"""M8.1 Step 5b — bulk email reveal honesty floor."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from app.services.contact_enrichment.step_5b_reveal_email import (
    _apply_honesty_floor,  # pyright: ignore[reportPrivateUsage]
    reveal_emails_for_contacts,
)


def _row(
    *,
    contact_id: str = "bc_dunkin_ap_1",
    linkedin_url: str | None = "https://linkedin.com/in/alice",
) -> MagicMock:
    """A fake BrandContact row carrying the fields Step 5b reads."""
    row = MagicMock()
    row.contact_id = contact_id
    row.brand_id = "dunkin"
    row.data = {"linkedin": {"url": linkedin_url}}
    return row


def _apollo_response(*, email: str | None, email_status: str | None) -> dict:
    return {"person": {"email": email, "email_status": email_status}}


# ── honesty floor pure-function tests ─────────────────────────────


def test_unit__honesty_floor__verified_email_kept() -> None:
    email, status = _apply_honesty_floor("a@b.com", "verified")
    assert email == "a@b.com"
    assert status == "verified"


def test_unit__honesty_floor__catchall_kept() -> None:
    email, status = _apply_honesty_floor("a@b.com", "catchall")
    assert email == "a@b.com"
    assert status == "catchall"


def test_unit__honesty_floor__unverified_stripped() -> None:
    email, status = _apply_honesty_floor("a@b.com", "unverified")
    assert email is None
    assert status == "unverified"


def test_unit__honesty_floor__bounced_stripped() -> None:
    email, status = _apply_honesty_floor("a@b.com", "bounced")
    assert email is None
    assert status == "bounced"


def test_unit__honesty_floor__missing_email_returns_not_found() -> None:
    email, status = _apply_honesty_floor(None, None)
    assert email is None
    assert status == "not_found"


def test_unit__honesty_floor__missing_status_with_email_treated_as_unverified() -> None:
    email, status = _apply_honesty_floor("a@b.com", None)
    assert email is None
    assert status == "unverified"


# ── reveal_emails_for_contacts integration ────────────────────────


@pytest.mark.asyncio
async def test_unit__reveal__empty_input_short_circuits() -> None:
    apollo = MagicMock()
    apollo.match_person = AsyncMock()
    repo = MagicMock()
    out = await reveal_emails_for_contacts(
        brand_id="dunkin",
        contact_ids=[],
        agency_id=UUID(int=0),
        repo=repo,
        apollo_client=apollo,
    )
    assert out == []
    apollo.match_person.assert_not_called()


@pytest.mark.asyncio
async def test_unit__reveal__verified_email_persists() -> None:
    apollo = MagicMock()
    apollo.match_person = AsyncMock(
        return_value=_apollo_response(email="alice@dunkin.com", email_status="verified")
    )
    repo = MagicMock()
    repo.get_by_brand_and_contact = AsyncMock(return_value=_row())
    repo.update_email_reveal = AsyncMock()

    results = await reveal_emails_for_contacts(
        brand_id="dunkin",
        contact_ids=["bc_dunkin_ap_1"],
        agency_id=UUID(int=0),
        repo=repo,
        apollo_client=apollo,
        brand_domain="dunkinbrands.com",
    )

    assert results[0]["email_revealed"] is True
    assert results[0]["verification_status"] == "verified"
    # Verify the write call to repo
    repo.update_email_reveal.assert_awaited_once()
    call_kwargs = repo.update_email_reveal.await_args.kwargs
    assert call_kwargs["email_address"] == "alice@dunkin.com"
    assert call_kwargs["verification_status"] == "verified"
    assert isinstance(call_kwargs["revealed_at"], datetime)


@pytest.mark.asyncio
async def test_unit__reveal__unverified_email_writes_status_but_no_email() -> None:
    apollo = MagicMock()
    apollo.match_person = AsyncMock(
        return_value=_apollo_response(email="guess@dunkin.com", email_status="unverified")
    )
    repo = MagicMock()
    repo.get_by_brand_and_contact = AsyncMock(return_value=_row())
    repo.update_email_reveal = AsyncMock()

    results = await reveal_emails_for_contacts(
        brand_id="dunkin",
        contact_ids=["bc_dunkin_ap_1"],
        agency_id=UUID(int=0),
        repo=repo,
        apollo_client=apollo,
        brand_domain="dunkinbrands.com",
    )

    assert results[0]["email_revealed"] is False
    assert results[0]["verification_status"] == "unverified"
    call_kwargs = repo.update_email_reveal.await_args.kwargs
    assert call_kwargs["email_address"] is None
    assert call_kwargs["verification_status"] == "unverified"


@pytest.mark.asyncio
async def test_unit__reveal__apollo_returns_no_email_marks_not_found() -> None:
    apollo = MagicMock()
    apollo.match_person = AsyncMock(return_value=_apollo_response(email=None, email_status=None))
    repo = MagicMock()
    repo.get_by_brand_and_contact = AsyncMock(return_value=_row())
    repo.update_email_reveal = AsyncMock()

    results = await reveal_emails_for_contacts(
        brand_id="dunkin",
        contact_ids=["bc_dunkin_ap_1"],
        agency_id=UUID(int=0),
        repo=repo,
        apollo_client=apollo,
        brand_domain="dunkinbrands.com",
    )

    assert results[0]["email_revealed"] is False
    assert results[0]["verification_status"] == "not_found"
    # Still records the attempt — revealed_at progresses.
    repo.update_email_reveal.assert_awaited_once()


@pytest.mark.asyncio
async def test_unit__reveal__apollo_exception_records_apollo_error() -> None:
    """Apollo failure on one contact doesn't kill the bulk run."""
    apollo = MagicMock()
    apollo.match_person = AsyncMock(side_effect=RuntimeError("Apollo down"))
    repo = MagicMock()
    repo.get_by_brand_and_contact = AsyncMock(return_value=_row())
    repo.update_email_reveal = AsyncMock()

    results = await reveal_emails_for_contacts(
        brand_id="dunkin",
        contact_ids=["bc_dunkin_ap_1"],
        agency_id=UUID(int=0),
        repo=repo,
        apollo_client=apollo,
        brand_domain="dunkinbrands.com",
    )

    assert results[0]["email_revealed"] is False
    assert results[0]["verification_status"] == "apollo_error"
    call_kwargs = repo.update_email_reveal.await_args.kwargs
    assert call_kwargs["email_address"] is None
    assert call_kwargs["verification_status"] == "apollo_error"


@pytest.mark.asyncio
async def test_unit__reveal__missing_contact_row_skips_apollo() -> None:
    """Contact_id pointing at a non-existent row is captured in result, no Apollo call."""
    apollo = MagicMock()
    apollo.match_person = AsyncMock()
    repo = MagicMock()
    repo.get_by_brand_and_contact = AsyncMock(return_value=None)
    repo.update_email_reveal = AsyncMock()

    results = await reveal_emails_for_contacts(
        brand_id="dunkin",
        contact_ids=["bc_missing"],
        agency_id=UUID(int=0),
        repo=repo,
        apollo_client=apollo,
        brand_domain="dunkinbrands.com",
    )

    assert results[0]["verification_status"] == "contact_not_found"
    apollo.match_person.assert_not_called()
    repo.update_email_reveal.assert_not_called()


@pytest.mark.asyncio
async def test_unit__reveal__bulk_fans_out_sequentially_per_contact() -> None:
    """Three contacts → three Apollo calls; results stay in input order."""
    apollo = MagicMock()
    apollo.match_person = AsyncMock(
        side_effect=[
            _apollo_response(email="a@x.com", email_status="verified"),
            _apollo_response(email="b@x.com", email_status="unverified"),
            _apollo_response(email=None, email_status=None),
        ]
    )
    repo = MagicMock()
    repo.get_by_brand_and_contact = AsyncMock(
        side_effect=[_row(contact_id=f"bc_{i}") for i in range(3)]
    )
    repo.update_email_reveal = AsyncMock()

    results = await reveal_emails_for_contacts(
        brand_id="dunkin",
        contact_ids=["bc_0", "bc_1", "bc_2"],
        agency_id=UUID(int=0),
        repo=repo,
        apollo_client=apollo,
        brand_domain="dunkinbrands.com",
    )

    assert [r["contact_id"] for r in results] == ["bc_0", "bc_1", "bc_2"]
    assert [r["email_revealed"] for r in results] == [True, False, False]
    assert apollo.match_person.await_count == 3
    assert repo.update_email_reveal.await_count == 3


@pytest.mark.asyncio
async def test_unit__reveal__revealed_at_is_utc_aware() -> None:
    """The revealed_at timestamp written to DB is timezone-aware UTC."""
    apollo = MagicMock()
    apollo.match_person = AsyncMock(
        return_value=_apollo_response(email="a@x.com", email_status="verified")
    )
    repo = MagicMock()
    repo.get_by_brand_and_contact = AsyncMock(return_value=_row())
    repo.update_email_reveal = AsyncMock()

    await reveal_emails_for_contacts(
        brand_id="dunkin",
        contact_ids=["bc_dunkin_ap_1"],
        agency_id=UUID(int=0),
        repo=repo,
        apollo_client=apollo,
        brand_domain="dunkinbrands.com",
    )

    revealed_at: datetime = repo.update_email_reveal.await_args.kwargs["revealed_at"]
    assert revealed_at.tzinfo == UTC
