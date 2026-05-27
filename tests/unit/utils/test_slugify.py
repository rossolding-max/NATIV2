"""Hardening tests for ``app.utils.slugify``.

Covers Unicode normalisation, emoji stripping, leading/trailing dash
trimming, and collision-suffix handling.
"""

from __future__ import annotations

import pytest

from app.utils.slugify import slugify


@pytest.mark.parametrize(
    ("input_text", "expected"),
    [
        ("Riley Carter", "riley-carter"),
        ("Renée Müller", "renee-muller"),
        ("ÁÉÍÓÚáéíóú", "aeiouaeiou"),
        ("  leading and trailing  ", "leading-and-trailing"),
        ("Hello World!", "hello-world"),
        ("multiple   spaces", "multiple-spaces"),
        ("Snake_case_Name", "snake-case-name"),
        ("dots.and.dots", "dots-and-dots"),
        ("A B C D", "a-b-c-d"),
        ("CamelCase", "camelcase"),
    ],
)
def test_unit__slugify_normalises_input(input_text: str, expected: str) -> None:
    assert slugify(input_text) == expected


def test_unit__slugify_strips_emoji() -> None:
    assert slugify("Riley 🎬 Carter") == "riley-carter"
    assert slugify("👋 Hi") == "hi"


def test_unit__slugify_strips_leading_trailing_dashes() -> None:
    # Symbol-only prefixes/suffixes generate leading/trailing dashes after
    # symbol-stripping; the regex trims them.
    assert slugify("---Hello---") == "hello"
    assert slugify("__Hello__") == "hello"


def test_unit__slugify_collision_suffix_starts_at_2() -> None:
    existing = {"riley-carter"}
    assert slugify("Riley Carter", existing=existing) == "riley-carter-2"


def test_unit__slugify_collision_increments_until_unique() -> None:
    existing = {"riley-carter", "riley-carter-2", "riley-carter-3"}
    assert slugify("Riley Carter", existing=existing) == "riley-carter-4"


def test_unit__slugify_no_collision_returns_base() -> None:
    existing = {"someone-else"}
    assert slugify("Riley Carter", existing=existing) == "riley-carter"


def test_unit__slugify_rejects_empty_input() -> None:
    for bad in ("", "   ", "\n\t"):
        with pytest.raises(ValueError, match="at least one alphanumeric"):
            slugify(bad)


def test_unit__slugify_rejects_pure_symbol_input() -> None:
    for bad in ("!!!", "---", "🎬🎬"):
        with pytest.raises(ValueError, match="empty slug"):
            slugify(bad)
