"""Write the per-brand ``brand_contacts`` JSON snapshot.

Atomic semantics: write to a temp file in the same directory then
``os.replace`` (atomic on POSIX). Reads the existing
``current/{brand_id}.json`` first and preserves the workflow-state
fields (``do_not_contact``, ``do_not_contact_reason``, ``opt_out_at``,
``pitch_history``, ``tags``, ``notes``, ``champion_for_talents``,
``first_discovered_at``) per the workflow doc § "Preserved fields".

Also writes an immutable per-run snapshot under
``data/brand_contacts/runs/{brand_id}/{run_id}.json`` for audit.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.contact_enrichment._models import (
    EnrichmentRunResult,
    QualifiedContact,
)
from app.utils.logging import get_logger

log = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CURRENT_DIR = _REPO_ROOT / "data" / "brand_contacts" / "current"
_RUNS_DIR = _REPO_ROOT / "data" / "brand_contacts" / "runs"

_PRESERVED_FIELDS: tuple[str, ...] = (
    "do_not_contact",
    "do_not_contact_reason",
    "opt_out_at",
    "pitch_history",
    "tags",
    "notes",
    "champion_for_talents",
    "first_discovered_at",
)


def _contact_to_dict(qc: QualifiedContact) -> dict[str, Any]:
    c = qc.contact
    data: dict[str, Any] = {
        "contact_id": c.contact_id,
        "brand_id": c.brand_id,
        "name": c.name,
        "title": c.title,
        "seniority": c.seniority,
        "function": c.function,
        "linkedin_url": c.linkedin_url,
        "decision_role": c.decision_role,
        "decision_role_rationale": c.decision_role_rationale,
        "email": (
            {"address": c.email_address, "verification_status": c.email_verification_status}
            if c.email_address
            else None
        ),
        "location": c.location,
        "sources": c.sources,
        "qualification": {
            "score": round(qc.qualification_score, 3),
            "tier": qc.qualification_tier,
            "signals": qc.qualification_signals,
        },
    }
    return data


def _load_existing_snapshot(brand_id: str) -> dict[str, Any]:
    path = _CURRENT_DIR / f"{brand_id}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("contact_snapshot_read_failed", brand_id=brand_id, error=str(exc))
        return {}


def _preserve_workflow_state(
    new_entries: list[dict[str, Any]],
    previous_by_contact_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Carry forward agent-driven workflow fields from the previous run."""
    now_iso = datetime.now(UTC).isoformat()
    out: list[dict[str, Any]] = []
    for entry in new_entries:
        contact_id = entry.get("contact_id")
        prev = previous_by_contact_id.get(contact_id) if contact_id else None
        merged = dict(entry)
        if prev is not None:
            for f in _PRESERVED_FIELDS:
                if f in prev:
                    merged[f] = prev[f]
            merged.setdefault("first_discovered_at", prev.get("first_discovered_at", now_iso))
        else:
            merged.setdefault("do_not_contact", False)
            merged.setdefault("first_discovered_at", now_iso)
        merged["last_enriched_at"] = now_iso
        out.append(merged)
    return out


def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
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


def write_snapshot(result: EnrichmentRunResult, *, version: str = "0.1") -> Path:
    """Write both ``current/`` and ``runs/`` snapshots. Returns the current path."""
    current_path = _CURRENT_DIR / f"{result.brand_id}.json"

    previous = _load_existing_snapshot(result.brand_id)
    previous_by_contact_id: dict[str, dict[str, Any]] = {}
    for entry in previous.get("contacts") or []:
        if isinstance(entry, dict) and entry.get("contact_id"):
            previous_by_contact_id[entry["contact_id"]] = entry

    contact_dicts = _preserve_workflow_state(
        [_contact_to_dict(c) for c in result.contacts], previous_by_contact_id
    )
    blocked_dicts = [_contact_to_dict(c) for c in result.blocked]

    payload = {
        "brand_id": result.brand_id,
        "version": version,
        "last_enriched_at": result.generated_at.isoformat(),
        "enrichment_run_id": result.run_id,
        "steps_run": result.steps_run,
        "contacts": contact_dicts,
        "blocked": blocked_dicts,
        "errors": result.errors,
        "talent_id_context": result.talent_id,
    }

    _atomic_write_json(current_path, payload)

    runs_path = _RUNS_DIR / result.brand_id / f"{result.run_id}.json"
    _atomic_write_json(runs_path, payload)

    log.info(
        "contact_snapshot_written",
        brand_id=result.brand_id,
        contact_count=len(contact_dicts),
        blocked_count=len(blocked_dicts),
        current=str(current_path),
        runs=str(runs_path),
    )
    return current_path


__all__: tuple[str, ...] = ("_contact_to_dict", "write_snapshot")
