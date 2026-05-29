"""Write the per-talent ``brand_candidates`` JSON snapshot.

Atomic semantics: write to a temp file in the same directory then
``os.replace`` (atomic on POSIX). Reads the existing
``current/{talent_id}.json`` first and preserves the workflow-state
fields (``status``, ``assigned_to``, ``user_notes``, ``pitch_history``,
``legal_entity_override``, ``first_surfaced_at``) per the workflow doc
§ "Preserved fields".

Also writes an immutable per-run snapshot under
``data/brand_candidates/runs/{talent_id}/run_{ts}.json`` for audit +
later mention-velocity analysis.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.discovery._models import DiscoveryRunResult, QualifiedCandidate
from app.utils.logging import get_logger

log = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CURRENT_DIR = _REPO_ROOT / "data" / "brand_candidates" / "current"
_RUNS_DIR = _REPO_ROOT / "data" / "brand_candidates" / "runs"


def _primary_source_search(candidate: QualifiedCandidate) -> str | None:
    """Return the search_tag of the heaviest-weight source for UI convenience.

    Sorted by weight desc then search_tag asc (alphabetical) for
    determinism — ties between equal-weight sources break the same way
    every run.
    """
    if not candidate.sources:
        return None
    ordered = sorted(candidate.sources, key=lambda s: (-s.weight, s.search_tag))
    return ordered[0].search_tag


def _candidate_to_dict(candidate: QualifiedCandidate) -> dict[str, Any]:
    data: dict[str, Any] = {
        "brand": candidate.brand_name,
        "brand_id": candidate.brand_id,
        "industry_id": candidate.industry_id,
        "score": round(candidate.score, 3),
        "tier": candidate.tier,
        "found_in_searches": len({s.search_tag for s in candidate.sources}),
        # M7.4 — top-level pointer at the highest-weight source so the
        # agent UI can render a single "discovered via X" tag without
        # iterating the sources list.
        "primary_source_search": _primary_source_search(candidate),
        "sources": [
            {
                "search": s.search_tag,
                "weight": s.weight,
                "note": s.note,
                # M7.5 — Exa provenance: present only for S15/S18 sources.
                "exa_query": s.exa_query,
                "exa_result_url": s.exa_result_url,
                "exa_result_title": s.exa_result_title,
            }
            for s in candidate.sources
        ],
        "qualification": {
            "score": round(candidate.qualification_score, 3),
            "tier": candidate.qualification_tier,
            "signals": candidate.qualification_signals,
        },
    }
    if candidate.warnings:
        data["warnings"] = candidate.warnings
    if candidate.blocked:
        data["blocked"] = True
        if candidate.block_reason:
            data["block_reason"] = candidate.block_reason
    return data


def _load_existing_snapshot(talent_id: str) -> dict[str, Any]:
    path = _CURRENT_DIR / f"{talent_id}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("snapshot_read_failed", talent_id=talent_id, error=str(exc))
        return {}


def _preserve_workflow_state(
    new_entries: list[dict[str, Any]], previous_by_brand_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Carry forward agent-driven workflow fields from previous run.

    Preserved per workflow doc § "Preserved fields": status,
    assigned_to, user_notes, pitch_history, legal_entity_override,
    first_surfaced_at, last_surfaced_at.
    """
    preserved_fields = (
        "status",
        "assigned_to",
        "user_notes",
        "pitch_history",
        "legal_entity_override",
        "first_surfaced_at",
    )
    now_iso = datetime.now(UTC).isoformat()
    out: list[dict[str, Any]] = []
    for entry in new_entries:
        brand_id = entry.get("brand_id")
        prev = previous_by_brand_id.get(brand_id) if brand_id else None
        merged = dict(entry)
        if prev is not None:
            for f in preserved_fields:
                if f in prev:
                    merged[f] = prev[f]
            # Keep the original surfaced timestamp.
            merged.setdefault("first_surfaced_at", prev.get("first_surfaced_at", now_iso))
        else:
            merged.setdefault("status", "new")
            merged.setdefault("first_surfaced_at", now_iso)
        merged["last_surfaced_at"] = now_iso
        out.append(merged)
    return out


def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``target`` atomically (temp file + os.replace)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    # NamedTemporaryFile must live in the same directory for os.replace to be atomic.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    ) as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
        tmp_path = Path(fh.name)
    os.replace(tmp_path, target)


def write_snapshot(result: DiscoveryRunResult, *, version: str = "0.1") -> Path:
    """Write both ``current/`` and ``runs/`` snapshots. Returns the current path."""
    current_path = _CURRENT_DIR / f"{result.talent_id}.json"

    previous = _load_existing_snapshot(result.talent_id)
    previous_by_brand_id: dict[str, dict[str, Any]] = {}
    for entry in previous.get("candidates") or []:
        if isinstance(entry, dict) and entry.get("brand_id"):
            previous_by_brand_id[entry["brand_id"]] = entry

    candidate_dicts = _preserve_workflow_state(
        [_candidate_to_dict(c) for c in result.candidates], previous_by_brand_id
    )
    blocked_dicts = [_candidate_to_dict(c) for c in result.blocked]

    payload = {
        "talent_id": result.talent_id,
        "version": version,
        "generated_at": result.generated_at.isoformat(),
        "search_run_id": result.search_run_id,
        "searches_run": result.searches_run,
        "candidates": candidate_dicts,
        "blocked": blocked_dicts,
        "errors": result.errors,
    }

    _atomic_write_json(current_path, payload)

    # Per-run immutable snapshot. Suffix the run id so concurrent runs
    # don't clobber each other.
    runs_path = _RUNS_DIR / result.talent_id / f"{result.search_run_id}.json"
    _atomic_write_json(runs_path, payload)

    log.info(
        "discovery_snapshot_written",
        talent_id=result.talent_id,
        candidate_count=len(candidate_dicts),
        blocked_count=len(blocked_dicts),
        current=str(current_path),
        runs=str(runs_path),
    )
    return current_path


# ``_candidate_to_dict`` is module-private but tests import it directly
# to verify the serialised shape.
__all__: tuple[str, ...] = ("_candidate_to_dict", "write_snapshot")
