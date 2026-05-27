"""Unit test for the Smartlead → internal warmup status translator."""

from __future__ import annotations

import pytest

from app.services import agency_warmup


def _translate_smartlead_warmup_status(s: str) -> str:
    return agency_warmup._translate_smartlead_warmup_status(s)  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ("smartlead", "expected"),
    [
        ("completed", "complete"),
        ("Complete", "complete"),
        ("active", "complete"),
        ("in_progress", "in_progress"),
        ("paused", "paused"),
        ("STOPPED", "paused"),
        ("pending", "pending"),
        ("not_started", "pending"),
        ("foo", "in_progress"),  # unknown → assume mid-warmup
        ("", "in_progress"),
    ],
)
def test_unit__warmup_status_translation(smartlead: str, expected: str) -> None:
    assert _translate_smartlead_warmup_status(smartlead) == expected
