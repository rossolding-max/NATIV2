"""M7.4 — Brand-name canonicalization for Exa-driven discovery.

LLM-extracted brand names from Searches 15 / 18 often come back with
corporate suffixes ("Ford Motor Company", "Apple Inc", "The Kroger Co")
that don't match the curated seed map's shorter canonical names
("Ford", "Apple", "Kroger"). Exact case-insensitive matching misses
these and emits them as net-new emerging-tier candidates — inflating
the count and polluting the agent's view with duplicates.

This module provides a heuristic suffix stripper + alias-aware matcher
that maps Exa hits to existing seed entries when possible. Brands that
genuinely don't match a seed entry still flow through as net-new.
"""

from __future__ import annotations

import re
from typing import Any

# Trailing corporate suffixes — longest first so "Motor Company" wins
# over "Company". Each suffix is matched at the END of the name only,
# after at least one preceding token, so "Group X" stays as "Group X" —
# the suffix can't eat the whole name.
_TRAILING_SUFFIXES: tuple[str, ...] = (
    "motor company",
    "corporation",
    "holdings",
    "limited",
    "company",
    "brands",
    "group",
    "corp",
    "plc",
    "inc",
    "llc",
    "ltd",
    "co",
)

_PUNCT_RE = re.compile(r"[^a-z0-9\s]+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_brand_name(name: str) -> str:
    """Return a lowercase, suffix-stripped, punctuation-light version of ``name``.

    Used as the join key when matching LLM-extracted brand names against
    the curated seed map. Idempotent (normalize(normalize(x)) == normalize(x)).
    """
    if not name:
        return ""
    cleaned = name.lower().strip()
    # Drop leading "the ".
    if cleaned.startswith("the "):
        cleaned = cleaned[4:]
    # Strip punctuation (& -> "", . -> "", , -> "").
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if not cleaned:
        return ""
    # Iteratively strip trailing corporate suffixes (longest first).
    # Guard: must keep at least one token after stripping.
    changed = True
    while changed:
        changed = False
        for suffix in _TRAILING_SUFFIXES:
            suffix_with_space = " " + suffix
            if cleaned.endswith(suffix_with_space):
                stripped = cleaned[: -len(suffix_with_space)].strip()
                if stripped:  # keep at least one token
                    cleaned = stripped
                    changed = True
                    break
    return cleaned


def find_canonical_seed_entry(
    name: str, seed_brands: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Match ``name`` against seed map entries (by name OR aliases).

    Returns the matching seed entry dict or None. The match is on the
    normalized form so "Ford Motor Company" → "ford" matches a seed
    entry with name "Ford". Aliases are checked the same way.

    The seed_brands list shape mirrors ``brand_industry_map.json``:
    each entry has at minimum ``brand_id``, ``name``; may have
    ``aliases: list[str]``.
    """
    normalized_query = normalize_brand_name(name)
    if not normalized_query:
        return None
    for entry in seed_brands:
        seed_name = entry.get("name")
        if seed_name and normalize_brand_name(seed_name) == normalized_query:
            return entry
        for alias in entry.get("aliases", []) or []:
            if normalize_brand_name(alias) == normalized_query:
                return entry
    return None
