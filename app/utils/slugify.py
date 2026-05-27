"""Slugify helper. See ``docs/id_conventions.md`` § 1 for the ID format spec.

Behaviour:

1. NFKD-normalise the input (decompose accented chars to base + diacritic).
2. Strip non-ASCII bytes (drops diacritics, emoji, CJK).
3. Lower-case.
4. Replace non-alphanumeric runs with a single dash.
5. Trim leading/trailing dashes.
6. If the result collides with ``existing`` slugs, append ``-2``, ``-3`` ...
   until unique.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_LEADING_TRAILING_DASH = re.compile(r"^-+|-+$")


def slugify(text: str, existing: Iterable[str] | None = None) -> str:
    """Return a kebab-case slug. Raises ``ValueError`` if the input cannot
    produce a non-empty slug.
    """
    if not text or not text.strip():
        raise ValueError("text must contain at least one alphanumeric character")

    normalized = unicodedata.normalize("NFKD", text)
    ascii_bytes = normalized.encode("ascii", "ignore")
    base = ascii_bytes.decode("ascii").lower()
    base = _NON_ALNUM.sub("-", base)
    base = _LEADING_TRAILING_DASH.sub("", base)

    if not base:
        raise ValueError(f"text {text!r} produced an empty slug after normalisation")

    if existing is None:
        return base

    existing_set = set(existing)
    if base not in existing_set:
        return base

    # Collision handling: append -2, -3, ... until unique.
    n = 2
    while f"{base}-{n}" in existing_set:
        n += 1
    return f"{base}-{n}"
