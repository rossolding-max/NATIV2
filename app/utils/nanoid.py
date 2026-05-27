"""Nanoid generation helpers. See ``docs/id_conventions.md`` § 2.

Two alphabets:

- ``NANOID_ALPHABET`` (64 chars, URL-safe ``A-Za-z0-9_-``) — the default.
  ~71 bits of entropy at length 12.
- ``MEMO_ALPHABET`` (36 chars, lowercase ``a-z0-9``) — memo IDs only,
  legacy from the initial schema.
"""

from __future__ import annotations

import secrets

NANOID_ALPHABET: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
"""64-char URL-safe alphabet. Used by every ID type except memos."""

MEMO_ALPHABET: str = "abcdefghijklmnopqrstuvwxyz0123456789"
"""36-char lowercase alphabet. Used by ``memo_<12>`` IDs (legacy)."""


def generate_nanoid(length: int, alphabet: str = NANOID_ALPHABET) -> str:
    """Return a cryptographically-random ID of ``length`` chars from ``alphabet``.

    Uses ``secrets.choice`` for unbiased selection.
    """
    if length < 1:
        raise ValueError("length must be >= 1")
    if not alphabet:
        raise ValueError("alphabet must be non-empty")
    return "".join(secrets.choice(alphabet) for _ in range(length))
