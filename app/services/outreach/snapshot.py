"""Write the per-enrollment JSON snapshot.

Atomic dual-write: ``current/{enrollment_id}.json`` + immutable
``runs/{enrollment_id}/{run_id}.json``. Reads existing current
snapshot first and preserves workflow-state fields per the M9 spec
(approved_at, killed_at, kill_reason, user_notes, events,
engagement_summary, smartlead_meta).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.services.outreach._models import EnrollmentRunResult
from app.utils.logging import get_logger

log = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CURRENT_DIR = _REPO_ROOT / "data" / "pitch_enrollments" / "current"
_RUNS_DIR = _REPO_ROOT / "data" / "pitch_enrollments" / "runs"

_PRESERVED_FIELDS: tuple[str, ...] = (
    "approved_at",
    "approved_by",
    "killed_at",
    "kill_reason",
    "user_notes",
    "events",
    "engagement_summary",
    "smartlead_meta",
    "created_deal_id",
)


def _serialise_steps(result: EnrollmentRunResult) -> list[dict[str, Any]]:
    if result.draft is None:
        return []
    return [
        {
            "step_number": s.step_number,
            "intent": s.intent,
            "subject": s.subject,
            "body": s.body,
            "angles_used": s.angles_used,
            "personalization_fields_used": s.personalization_fields_used,
            "reasoning": s.reasoning,
            "model_used": s.model_used,
            "timing_offset_days": s.timing_offset_days,
            "validation_warnings": s.validation_warnings,
        }
        for s in result.draft.steps
    ]


def _load_existing(enrollment_id: str) -> dict[str, Any]:
    path = _CURRENT_DIR / f"{enrollment_id}.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("snapshot_read_failed", enrollment_id=enrollment_id, error=str(exc))
        return {}


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


def write_snapshot(result: EnrollmentRunResult, *, version: str = "0.1") -> Path | None:
    """Write both current/ + runs/. Returns the current path (or None on block)."""
    if result.draft is None:
        return None
    enrollment_id = result.draft.enrollment_id
    current = _load_existing(enrollment_id)
    preserved = {k: current[k] for k in _PRESERVED_FIELDS if k in current}

    payload: dict[str, Any] = {
        "enrollment_id": enrollment_id,
        "version": version,
        "run_id": result.run_id,
        "generated_at": result.generated_at.isoformat(),
        "talent_id": result.talent_id,
        "contact_id": result.contact_id,
        "brand_id": result.brand_id,
        "template_id": result.draft.template_id,
        "state": "awaiting_approval",
        "steps": _serialise_steps(result),
        "sources_summary": result.draft.sources_summary,
        "warnings": result.warnings,
        "errors": result.errors,
        **preserved,
    }
    payload.setdefault(
        "engagement_summary",
        {
            "sent": 0,
            "delivered": 0,
            "opened": 0,
            "clicked": 0,
            "replied": 0,
            "bounced": 0,
        },
    )

    current_path = _CURRENT_DIR / f"{enrollment_id}.json"
    runs_path = _RUNS_DIR / enrollment_id / f"{result.run_id}.json"
    _atomic_write_json(current_path, payload)
    _atomic_write_json(runs_path, payload)
    log.info(
        "outreach_snapshot_written",
        enrollment_id=enrollment_id,
        run_id=result.run_id,
        steps=len(payload["steps"]),
        current=str(current_path),
        runs=str(runs_path),
    )
    return current_path


__all__: tuple[str, ...] = ("write_snapshot",)
