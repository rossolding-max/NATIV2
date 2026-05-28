"""Outreach policy filter — DNC + active enrollment + 14-day cooldown."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock

from app.services.outreach import policy_filter


def _contact(
    *,
    do_not_contact: bool = False,
    pitch_history: list[dict[str, Any]] | None = None,
) -> MagicMock:
    c = MagicMock()
    c.do_not_contact = do_not_contact
    c.data = {"pitch_history": pitch_history or []}
    return c


def _enrollment(*, talent_id: str, state: str) -> MagicMock:
    e = MagicMock()
    e.talent_id = talent_id
    e.state = state
    return e


def test_unit__policy__dnc_blocks() -> None:
    ok, reason = policy_filter.is_eligible(
        contact=_contact(do_not_contact=True),
        talent_id="t-1",
        active_enrollments=[],
    )
    assert ok is False
    assert reason == "do_not_contact"


def test_unit__policy__active_enrollment_for_same_talent_blocks() -> None:
    ok, reason = policy_filter.is_eligible(
        contact=_contact(),
        talent_id="t-1",
        active_enrollments=[_enrollment(talent_id="t-1", state="active")],
    )
    assert ok is False
    assert reason == "active_enrollment_for_talent"


def test_unit__policy__active_enrollment_for_other_talent_doesnt_block() -> None:
    """Shared-roster semantics — other talent's enrollment leaves this talent free."""
    ok, reason = policy_filter.is_eligible(
        contact=_contact(),
        talent_id="t-1",
        active_enrollments=[_enrollment(talent_id="t-2", state="active")],
    )
    assert ok is True
    assert reason is None


def test_unit__policy__recent_pitch_for_same_talent_blocks() -> None:
    now = datetime.now(UTC)
    history = [{"talent_id": "t-1", "pitched_at": (now - timedelta(days=3)).isoformat()}]
    ok, reason = policy_filter.is_eligible(
        contact=_contact(pitch_history=history),
        talent_id="t-1",
        active_enrollments=[],
        today=now,
    )
    assert ok is False
    assert reason == "pitched_within_cooldown"


def test_unit__policy__old_pitch_doesnt_block() -> None:
    now = datetime.now(UTC)
    history = [{"talent_id": "t-1", "pitched_at": (now - timedelta(days=30)).isoformat()}]
    ok, _ = policy_filter.is_eligible(
        contact=_contact(pitch_history=history),
        talent_id="t-1",
        active_enrollments=[],
        today=now,
    )
    assert ok is True


def test_unit__policy__recent_pitch_for_other_talent_doesnt_block() -> None:
    now = datetime.now(UTC)
    history = [{"talent_id": "t-2", "pitched_at": (now - timedelta(days=3)).isoformat()}]
    ok, _ = policy_filter.is_eligible(
        contact=_contact(pitch_history=history),
        talent_id="t-1",
        active_enrollments=[],
        today=now,
    )
    assert ok is True


def test_unit__policy__clean_contact_eligible() -> None:
    ok, reason = policy_filter.is_eligible(
        contact=_contact(),
        talent_id="t-1",
        active_enrollments=[],
    )
    assert ok is True
    assert reason is None
