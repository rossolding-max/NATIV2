"""M7.4 — Atomic appender for ``data/brand_industry_map_discovered.json``.

Called at the end of every discovery run. For each candidate whose
``brand_id`` doesn't already exist in the curated seed map or in the
current discovered file, appends an entry so future runs across all
the agency's talents can match on it via Search 5/6/7.

Atomicity: writes to a temp file alongside the target then ``os.replace``
swaps. Concurrent Celery workers race; for v1 we accept eventual
consistency (last writer wins).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.discovery._brand_normalizer import normalize_brand_name
from app.services.discovery._seed_map_loader import (
    CURATED_FILENAME,
    DISCOVERED_FILENAME,
)
from app.utils.logging import get_logger

log = get_logger(__name__)


def _discovered_path(data_dir: Path | None = None) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return (data_dir or repo_root / "data") / DISCOVERED_FILENAME


def _curated_path(data_dir: Path | None = None) -> Path:
    repo_root = Path(__file__).resolve().parents[3]
    return (data_dir or repo_root / "data") / CURATED_FILENAME


def _existing_keys(brands: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for entry in brands:
        for value in (entry.get("name"), entry.get("brand_id")):
            if isinstance(value, str):
                normalized = normalize_brand_name(value)
                if normalized:
                    keys.add(normalized)
    return keys


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON to a temp file in the same dir, then ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        dir=path.parent,
        prefix=f".{path.name}.tmp.",
        delete=False,
        encoding="utf-8",
    ) as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        tmp_path = Path(fh.name)
    os.replace(tmp_path, path)


_MAX_PROVENANCE = 5  # cap discovery_provenance per brand to bound file size


def _build_provenance_entries(payload: dict[str, Any], search_run_id: str) -> list[dict[str, Any]]:
    """Pluck (search, exa_query, exa_result_url) triples from S15/S18 sources
    in the candidate payload. Used for both fresh appends and merge updates.
    """
    out: list[dict[str, Any]] = []
    for s in payload.get("sources") or []:
        if not isinstance(s, dict):
            continue
        if not s.get("exa_query"):
            continue
        out.append(
            {
                "search": s.get("search"),
                "exa_query": s.get("exa_query"),
                "exa_result_url": s.get("exa_result_url"),
                "exa_result_title": s.get("exa_result_title"),
                "first_surfaced_in_run": search_run_id,
            }
        )
    return out


def _merge_social_handles(
    existing: dict[str, Any] | None, incoming: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Merge two social-handle dicts; first non-null wins per platform."""
    if not existing and not incoming:
        return None
    merged: dict[str, Any] = dict(existing or {})
    for platform, value in (incoming or {}).items():
        if value and not merged.get(platform):
            merged[platform] = value
    return merged or None


def append_discovered_brands(
    candidate_payloads: list[dict[str, Any]],
    *,
    data_dir: Path | None = None,
    search_run_id: str = "",
) -> int:
    """Append net-new brands to the discovered seed-map JSON; merge new info
    onto existing entries when the same brand reappears in a later run.

    For each candidate:
      - Net-new (name not in curated/discovered): append with full
        domain + social_handles + discovery_provenance (M7.5).
      - Already in discovered: merge any new domain, social handles, or
        provenance entries (capped to ``_MAX_PROVENANCE`` most recent).

    Returns the number of brands added OR updated.
    """
    if not candidate_payloads:
        return 0
    discovered_path = _discovered_path(data_dir)
    curated_path = _curated_path(data_dir)

    discovered_payload: dict[str, Any] = {"version": 1, "brands": []}
    if discovered_path.exists():
        try:
            discovered_payload = json.loads(discovered_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("discovered_seed_map_read_failed", error=str(exc))
            discovered_payload = {"version": 1, "brands": []}

    curated_brands: list[dict[str, Any]] = []
    if curated_path.exists():
        try:
            curated_payload = json.loads(curated_path.read_text(encoding="utf-8"))
            curated_brands = curated_payload.get("brands") or []
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("curated_seed_map_read_failed", error=str(exc))

    discovered_brands: list[dict[str, Any]] = list(discovered_payload.get("brands") or [])
    curated_keys = _existing_keys(curated_brands)
    # Index discovered by normalized name for merge updates.
    discovered_by_key: dict[str, dict[str, Any]] = {}
    for entry in discovered_brands:
        for value in (entry.get("name"), entry.get("brand_id")):
            if isinstance(value, str):
                normalized = normalize_brand_name(value)
                if normalized:
                    discovered_by_key.setdefault(normalized, entry)
                    break

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    appended = 0
    updated = 0
    for payload in candidate_payloads:
        name = payload.get("brand")
        brand_id = payload.get("brand_id")
        industry_id = payload.get("industry_id")
        if not isinstance(name, str) or not isinstance(brand_id, str):
            continue
        if not isinstance(industry_id, str) or not industry_id:
            continue
        normalized = normalize_brand_name(name)
        if not normalized:
            continue
        # Curated wins — don't write back over hand-curated entries.
        if normalized in curated_keys:
            continue
        provenance = _build_provenance_entries(payload, search_run_id)
        if normalized in discovered_by_key:
            # Merge update path.
            existing = discovered_by_key[normalized]
            changed = False
            if payload.get("domain") and not existing.get("domain"):
                existing["domain"] = payload["domain"]
                changed = True
            merged_social = _merge_social_handles(
                existing.get("social_handles"), payload.get("social_handles")
            )
            if merged_social != existing.get("social_handles") and merged_social:
                existing["social_handles"] = merged_social
                changed = True
            if provenance:
                existing_prov = list(existing.get("discovery_provenance") or [])
                # Append new provenance entries, dedupe by (search, exa_query, exa_result_url).
                seen = {
                    (p.get("search"), p.get("exa_query"), p.get("exa_result_url"))
                    for p in existing_prov
                    if isinstance(p, dict)
                }
                added_any = False
                for new in provenance:
                    key = (new.get("search"), new.get("exa_query"), new.get("exa_result_url"))
                    if key in seen:
                        continue
                    existing_prov.append(new)
                    seen.add(key)
                    added_any = True
                if added_any:
                    existing["discovery_provenance"] = existing_prov[-_MAX_PROVENANCE:]
                    changed = True
            if changed:
                existing["updated_at"] = now_iso
                updated += 1
            continue
        # Net-new path.
        new_entry: dict[str, Any] = {
            "brand_id": brand_id,
            "name": name,
            "industry_id": industry_id,
            "source": payload.get("primary_source_search") or "discovery_run",
            "first_surfaced_in_run": search_run_id,
            "discovered_at": now_iso,
        }
        # M7.7 — first-class brand metadata for downstream Search 5/6/7 walks.
        if payload.get("sub_industry_id"):
            new_entry["sub_industry_id"] = payload["sub_industry_id"]
        if payload.get("brand_category"):
            new_entry["brand_category"] = payload["brand_category"]
        if payload.get("domain"):
            new_entry["domain"] = payload["domain"]
        if payload.get("social_handles"):
            new_entry["social_handles"] = payload["social_handles"]
        if provenance:
            new_entry["discovery_provenance"] = provenance[-_MAX_PROVENANCE:]
        discovered_brands.append(new_entry)
        discovered_by_key[normalized] = new_entry
        appended += 1

    if appended == 0 and updated == 0:
        return 0

    discovered_payload["brands"] = discovered_brands
    discovered_payload["updated"] = now_iso
    discovered_payload["version"] = discovered_payload.get("version", 1)
    _atomic_write(discovered_path, discovered_payload)
    log.info(
        "discovered_seed_map_appended",
        added=appended,
        updated=updated,
        total=len(discovered_brands),
    )
    return appended + updated
