"""Unit tests for the Step 1 seed service (no Docker — sync logic only)."""

from __future__ import annotations

import pytest

from app.errors import ValidationError
from app.services.talent_seed import defaults_for_country, derive_slug


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Jane Doe", "jane-doe"),
        ("Acme Talent Inc.", "acme-talent-inc"),
        ("MULTIPLE   spaces", "multiple-spaces"),
        ("with-hyphens-keeps-them", "with-hyphens-keeps-them"),
    ],
)
def test_unit__derive_slug(name: str, expected: str) -> None:
    assert derive_slug(name) == expected


def test_unit__derive_slug__non_alpha__raises() -> None:
    with pytest.raises(ValidationError):
        derive_slug("!!!")


@pytest.mark.parametrize(
    ("country", "expected_tz"),
    [
        ("US", "America/Los_Angeles"),
        ("GB", "Europe/London"),
        ("UK", "Europe/London"),
        ("DE", "Europe/Berlin"),
        ("XX", "UTC"),  # unknown country
        (None, "UTC"),
    ],
)
def test_unit__defaults_for_country(country: str | None, expected_tz: str) -> None:
    defaults = defaults_for_country(country)
    assert defaults["timezone"] == expected_tz
    assert defaults["disclosure_style"].startswith("#")


def test_unit__defaults_for_country__lowercase_input() -> None:
    """Country codes are case-insensitive."""
    defaults = defaults_for_country("us")
    assert defaults["timezone"] == "America/Los_Angeles"
