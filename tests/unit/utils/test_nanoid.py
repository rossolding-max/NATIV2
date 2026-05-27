"""Hardening tests for ``app.utils.nanoid``.

Verifies the two alphabets are wired correctly and ``generate_nanoid`` honours
the documented contract.
"""

from __future__ import annotations

import string

import pytest

from app.utils.nanoid import MEMO_ALPHABET, NANOID_ALPHABET, generate_nanoid


def test_unit__nanoid_default_alphabet_is_64_chars_urlsafe() -> None:
    assert len(NANOID_ALPHABET) == 64
    expected = string.ascii_uppercase + string.ascii_lowercase + string.digits + "_-"
    assert set(NANOID_ALPHABET) == set(expected)


def test_unit__memo_alphabet_is_36_chars_lowercase() -> None:
    assert len(MEMO_ALPHABET) == 36
    expected = string.ascii_lowercase + string.digits
    assert set(MEMO_ALPHABET) == set(expected)


def test_unit__nanoid_default_uses_64_char_alphabet() -> None:
    sample = "".join(generate_nanoid(8) for _ in range(200))
    # Output must be a subset of NANOID_ALPHABET (chars only)
    assert set(sample) <= set(NANOID_ALPHABET)


def test_unit__nanoid_with_memo_alphabet_is_lowercase_only() -> None:
    sample = "".join(generate_nanoid(12, alphabet=MEMO_ALPHABET) for _ in range(200))
    assert set(sample) <= set(MEMO_ALPHABET)
    assert not any(c.isupper() for c in sample)


def test_unit__nanoid_respects_length() -> None:
    for n in (1, 5, 12, 32, 64):
        assert len(generate_nanoid(n)) == n


def test_unit__nanoid_collision_resistance_property() -> None:
    """At length 12 in a 64-char alphabet, 50k draws yield no duplicates."""
    seen: set[str] = set()
    n = 50_000
    for _ in range(n):
        seen.add(generate_nanoid(12))
    assert len(seen) == n, f"collision rate non-zero: {n - len(seen)} dupes / {n}"


def test_unit__nanoid_rejects_invalid_length() -> None:
    with pytest.raises(ValueError, match="length"):
        generate_nanoid(0)
    with pytest.raises(ValueError, match="length"):
        generate_nanoid(-1)


def test_unit__nanoid_rejects_empty_alphabet() -> None:
    with pytest.raises(ValueError, match="alphabet"):
        generate_nanoid(10, alphabet="")
