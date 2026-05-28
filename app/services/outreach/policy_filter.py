"""Outreach-eligibility policy filter.

Mirrors the shape of ``contact_enrichment/policy_filter.py``: returns
``(eligible: bool, reason: str | None)``. Blocks:

- ``do_not_contact == True`` on the contact.
- An ``active`` or ``awaiting_approval`` enrollment for the SAME
  ``(contact_id, talent_id)`` pair (no concurrent campaigns).
- A pitch to this contact by THIS talent within the last 14 days
  (shared-roster cooldown — does NOT block when a DIFFERENT talent
  pitched the same contact).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.models.sqla.brand_contact import BrandContact
from app.models.sqla.pitch_enrollment import PitchEnrollment

DEFAULT_COOLDOWN_DAYS: int = 14
_BLOCKING_STATES: frozenset[str] = frozenset({"awaiting_approval", "active", "paused"})


def _parse_when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def is_eligible(
    *,
    contact: BrandContact,
    talent_id: str,
    active_enrollments: list[PitchEnrollment],
    today: datetime | None = None,
    cooldown_days: int = DEFAULT_COOLDOWN_DAYS,
) -> tuple[bool, str | None]:
    """Return (eligible, reason). When eligible=True, reason is None."""
    now = today or datetime.now(UTC)

    if getattr(contact, "do_not_contact", False) is True:
        return False, "do_not_contact"

    for e in active_enrollments:
        if e.talent_id == talent_id and e.state in _BLOCKING_STATES:
            return False, "active_enrollment_for_talent"

    cutoff = now - timedelta(days=cooldown_days)
    history = (contact.data or {}).get("pitch_history") or []
    if isinstance(history, list):
        for entry in history:
            if not isinstance(entry, dict):
                continue
            if entry.get("talent_id") != talent_id:
                continue
            ts = _parse_when(entry.get("pitched_at") or entry.get("created_at"))
            if ts is None or ts < cutoff:
                continue
            return False, "pitched_within_cooldown"

    return True, None
