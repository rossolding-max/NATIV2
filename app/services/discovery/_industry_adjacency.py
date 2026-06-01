"""M7.7+ — Cross-sector industry adjacency lookup.

Loads ``data/industry_adjacency.json`` (a flat list of bidirectional
{from, to, reason} pairs) and exposes a single-industry lookup that
returns adjacent industries with their reasons.

Adjacencies are BIDIRECTIONAL — a pair {from: hotels, to: luggage}
matches lookups for both ``hotels`` and ``luggage``.

Adjacencies complement the taxonomy-driven bidirectional walk in
``_industry_expansion.py``: that walk goes UP to the parent + ACROSS
to siblings within the same top-level sector. Adjacencies capture
commercial / purchase-intent overlaps that cross sectors (e.g. hotels
↔ luggage, even though they sit under travel-hospitality vs
fashion-accessories).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.utils.logging import get_logger

log = get_logger(__name__)


_FILENAME = "industry_adjacency.json"


@lru_cache(maxsize=1)
def _load_adjacency_index() -> dict[str, list[tuple[str, str]]]:
    """Return ``{industry_id: [(adjacent_industry_id, reason), ...]}``.

    Bidirectional: a pair ``{from: A, to: B, reason: R}`` appears in
    both ``index[A]`` (as ``(B, R)``) and ``index[B]`` (as ``(A, R)``).

    Result is cached for the process lifetime — the file is small +
    deterministic. Tests that need to vary the data use a fresh
    fixture path and call ``_load_one_pair_list`` directly.
    """
    path = Path(__file__).resolve().parents[3] / "data" / _FILENAME
    if not path.exists():
        log.warning("industry_adjacency_file_missing", path=str(path))
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("industry_adjacency_file_unreadable", error=str(exc))
        return {}
    raw_pairs = payload.get("adjacencies") or []
    return _build_index_from_pairs(raw_pairs)


def _build_index_from_pairs(
    pairs: list[dict[str, str]],
) -> dict[str, list[tuple[str, str]]]:
    """Build the bidirectional ``{industry: [(adj, reason), ...]}`` index."""
    out: dict[str, list[tuple[str, str]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for entry in pairs or []:
        if not entry:
            continue
        a = (entry.get("from") or "").strip()
        b = (entry.get("to") or "").strip()
        reason = (entry.get("reason") or "").strip()
        if not a or not b or a == b:
            continue
        key = (a, b, reason)
        if key in seen:
            continue
        seen.add(key)
        out.setdefault(a, []).append((b, reason))
        out.setdefault(b, []).append((a, reason))
    return out


def adjacent_industries(
    industry_id: str, *, pairs: list[dict[str, str]] | None = None
) -> list[tuple[str, str]]:
    """Return the list of ``(adjacent_industry_id, reason)`` for ``industry_id``.

    Optional ``pairs`` arg lets tests inject a fresh adjacency table
    without relying on the file system + cache.
    """
    index = _build_index_from_pairs(pairs) if pairs is not None else _load_adjacency_index()
    return list(index.get(industry_id, []))
