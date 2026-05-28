"""Policy filter — DNC + per-talent cooldown + qualification threshold.

Blocks (drops from outreach pool):
- ``do_not_contact=True`` on the existing brand_contact row — permanent.
- Contact already pitched by THIS talent in the last 14 days (per-talent
  cooldown; shared-roster semantics — a contact pitched by a DIFFERENT
  talent stays kept).
- Qualification score below threshold (default 0.30 → ``unqualified``).

Returns ``(kept, blocked)`` two-tuple mirroring ``discovery/policy_filter.apply_filters``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.contact_enrichment._models import QualifiedContact

DEFAULT_COOLDOWN_DAYS: int = 14


def _parse_when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _recent_pitch_for_talent(
    *,
    pitch_history: list[Any],
    talent_id: str,
    today: datetime,
    cooldown_days: int,
) -> dict[str, Any] | None:
    """Return the most recent pitch entry for this talent within the cooldown."""
    cutoff = today - timedelta(days=cooldown_days)
    most_recent: tuple[datetime, dict[str, Any]] | None = None
    for entry in pitch_history or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("talent_id") != talent_id:
            continue
        ts = _parse_when(entry.get("created_at") or entry.get("sent_at"))
        if ts is None or ts < cutoff:
            continue
        if most_recent is None or ts > most_recent[0]:
            most_recent = (ts, entry)
    return most_recent[1] if most_recent else None


def apply_contact_filters(
    contacts: list[QualifiedContact],
    *,
    existing_workflow: dict[str, dict[str, Any]] | None = None,
    talent_id: str | None = None,
    qualification_threshold: float = 0.30,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
    today: datetime | None = None,
) -> tuple[list[QualifiedContact], list[QualifiedContact]]:
    """Partition contacts into kept + blocked.

    ``existing_workflow`` maps ``contact_id -> {do_not_contact, pitch_history,
    ...}`` from the persisted row (if any). Used for DNC + cooldown checks.
    """
    workflow = existing_workflow or {}
    now = today or datetime.now(UTC)

    kept: list[QualifiedContact] = []
    blocked: list[QualifiedContact] = []

    for q in contacts:
        existing = workflow.get(q.contact.contact_id) or {}
        # 1) Permanent honour-opt-out.
        if existing.get("do_not_contact") is True:
            blocked.append(q)
            continue
        # 2) Qualification threshold.
        if q.qualification_score < qualification_threshold:
            blocked.append(q)
            continue
        # 3) Per-talent 14-day cooldown.
        if talent_id:
            recent = _recent_pitch_for_talent(
                pitch_history=existing.get("pitch_history") or [],
                talent_id=talent_id,
                today=now,
                cooldown_days=cooldown_days,
            )
            if recent is not None:
                blocked.append(q)
                continue
        kept.append(q)

    return kept, blocked
