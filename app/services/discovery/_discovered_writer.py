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


def append_discovered_brands(
    candidate_payloads: list[dict[str, Any]],
    *,
    data_dir: Path | None = None,
    search_run_id: str = "",
) -> int:
    """Append net-new brands to the discovered seed-map JSON.

    A candidate is "net-new" when its normalised brand name does not
    already appear in either the curated or the discovered file.

    Returns the number of brands appended.
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
    existing_normalized = _existing_keys(curated_brands) | _existing_keys(discovered_brands)

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    appended = 0
    for payload in candidate_payloads:
        name = payload.get("brand")
        brand_id = payload.get("brand_id")
        industry_id = payload.get("industry_id")
        if not isinstance(name, str) or not isinstance(brand_id, str):
            continue
        if not isinstance(industry_id, str) or not industry_id:
            continue
        normalized = normalize_brand_name(name)
        if not normalized or normalized in existing_normalized:
            continue
        existing_normalized.add(normalized)
        discovered_brands.append(
            {
                "brand_id": brand_id,
                "name": name,
                "industry_id": industry_id,
                "source": payload.get("primary_source_search") or "discovery_run",
                "first_surfaced_in_run": search_run_id,
                "discovered_at": now_iso,
            }
        )
        appended += 1

    if appended == 0:
        return 0

    discovered_payload["brands"] = discovered_brands
    discovered_payload["updated"] = now_iso
    discovered_payload["version"] = discovered_payload.get("version", 1)
    _atomic_write(discovered_path, discovered_payload)
    log.info("discovered_seed_map_appended", added=appended, total=len(discovered_brands))
    return appended
