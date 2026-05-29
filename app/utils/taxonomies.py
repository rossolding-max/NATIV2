"""In-memory reference taxonomies loaded at lifespan startup.

These files are static reference data per ``docs/architecture.md`` § 7:
- ``data/niches.json`` — 2-level content niche taxonomy.
- ``data/industries.json`` — 2-level brand industry taxonomy.
- ``data/industry_audience_affinity.json`` — industry → IAB segment maps.
- ``data/niche_audience_affinity.json`` — niche → IAB segment maps.
- ``data/niche_industry_affinity.json`` — niche ↔ industry strength matrix.
- ``data/brand_competitors.json`` — brand → competitor[] graph.
- ``data/iab_audience_taxonomy_v1.1.json`` — IAB Audience Taxonomy v1.1 segments.

Loaded once at lifespan startup; never mutated; not stored in Postgres
(reference data; no query benefit per the M1 plan locked decision).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Project root resolved from this file's location. The data files live under
# ``<repo>/data/``. Override via ``Taxonomies.from_directory`` for tests.
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"


@dataclass
class Taxonomies:
    """Loaded reference data. Exposes lookup helpers used across the app."""

    niches: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    industries: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    industry_audience_affinity: dict[str, Any] = field(default_factory=dict[str, Any])
    niche_audience_affinity: dict[str, Any] = field(default_factory=dict[str, Any])
    niche_industry_affinity: dict[str, Any] = field(default_factory=dict[str, Any])
    brand_competitors: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    iab_segments: dict[int, dict[str, Any]] = field(default_factory=dict[int, dict[str, Any]])

    # M7.3 — pre-built reverse index of `parent -> [children]` for fast
    # sub-industry expansion in the discovery searches. Built once in
    # ``from_directory``.
    _industry_children: dict[str, list[str]] = field(default_factory=dict[str, list[str]])

    # ── Construction ──────────────────────────────────────────────────

    @classmethod
    def from_directory(cls, data_dir: Path) -> Taxonomies:
        """Load all taxonomy files from ``data_dir``. Raises if any file is missing."""

        def _load(name: str) -> Any:
            path = data_dir / name
            if not path.exists():
                raise FileNotFoundError(f"Required taxonomy file missing: {path}")
            return json.loads(path.read_text(encoding="utf-8"))

        niches_doc = _load("niches.json")
        industries_doc = _load("industries.json")
        industry_affinity_doc = _load("industry_audience_affinity.json")
        niche_affinity_doc = _load("niche_audience_affinity.json")
        niche_industry_doc = _load("niche_industry_affinity.json")
        competitors_doc = _load("brand_competitors.json")
        iab_doc = _load("iab_audience_taxonomy_v1.1.json")

        niches = {n["id"]: n for n in niches_doc["niches"]}
        industries = {i["id"]: i for i in industries_doc["industries"]}
        competitors_map: dict[str, list[str]] = competitors_doc.get("competitors") or {}
        iab_segments = {s["id"]: s for s in iab_doc.get("segments", [])}

        # Pre-compute parent -> children index for fast sub-industry walks.
        industry_children: dict[str, list[str]] = {}
        for industry_id, node in industries.items():
            parent = node.get("parent")
            if isinstance(parent, str) and parent:
                industry_children.setdefault(parent, []).append(industry_id)
        # Sort each child list for deterministic discovery output.
        for parent in industry_children:
            industry_children[parent].sort()

        return cls(
            niches=niches,
            industries=industries,
            industry_audience_affinity=industry_affinity_doc,
            niche_audience_affinity=niche_affinity_doc,
            niche_industry_affinity=niche_industry_doc,
            brand_competitors=competitors_map,
            iab_segments=iab_segments,
            _industry_children=industry_children,
        )

    # ── Niche helpers ─────────────────────────────────────────────────

    def get_niche(self, niche_id: str) -> dict[str, Any] | None:
        return self.niches.get(niche_id)

    def is_valid_niche_id(self, niche_id: str) -> bool:
        return niche_id in self.niches

    def get_niche_parent(self, niche_id: str) -> str | None:
        node = self.niches.get(niche_id)
        return node.get("parent") if node else None

    # ── Industry helpers ──────────────────────────────────────────────

    def get_industry(self, industry_id: str) -> dict[str, Any] | None:
        return self.industries.get(industry_id)

    def is_valid_industry_id(self, industry_id: str) -> bool:
        return industry_id in self.industries

    def get_industry_parent(self, industry_id: str) -> str | None:
        node = self.industries.get(industry_id)
        return node.get("parent") if node else None

    def is_sensitive_industry(self, industry_id: str) -> bool:
        node = self.industries.get(industry_id)
        return bool(node and node.get("sensitive"))

    def get_sub_industries(self, industry_id: str) -> list[str]:
        """Return immediate child industry ids for ``industry_id``.

        M7.3 — the discovery industry-tier searches use this to expand a
        target parent industry into all of its sub-industries (e.g.
        ``sports-outdoor`` -> ``sportswear``, ``outdoor-gear``,
        ``gym-equipment``, ...). Empty list for leaf industries.
        """
        return list(self._industry_children.get(industry_id, []))

    # ── Competitor lookup ─────────────────────────────────────────────

    def get_competitors(self, brand_name: str) -> list[str]:
        return list(self.brand_competitors.get(brand_name, []))

    # ── IAB segment lookup ────────────────────────────────────────────

    def get_iab_segment(self, segment_id: int) -> dict[str, Any] | None:
        return self.iab_segments.get(segment_id)


# ── Module-level singleton + lifespan binding ─────────────────────────

_singleton: Taxonomies | None = None


def init_taxonomies(data_dir: Path | None = None) -> Taxonomies:
    """Load taxonomies into the module-level singleton. Called from lifespan."""
    global _singleton
    _singleton = Taxonomies.from_directory(data_dir or _DEFAULT_DATA_DIR)
    return _singleton


def get_taxonomies() -> Taxonomies:
    """Return the loaded singleton. Raises if ``init_taxonomies`` hasn't run."""
    if _singleton is None:
        raise RuntimeError(
            "Taxonomies not initialised. Call init_taxonomies() in the app lifespan."
        )
    return _singleton


def is_loaded() -> bool:
    """Return ``True`` if the singleton has been initialised. Used by /health."""
    return _singleton is not None
