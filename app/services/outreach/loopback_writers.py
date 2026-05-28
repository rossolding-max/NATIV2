"""M6 ↔ M9 and M8 ↔ M9 loopback writers.

- ``append_pitch_history``: M8 ↔ M9 — every time an enrollment is
  generated (or moves to ``active``), append a per-(contact, talent)
  entry to ``brand_contact.data.pitch_history[]``. M8's policy filter
  reads this for the 14-day cooldown.
- ``set_re_engagement_pitch_date``: M6 ↔ M9 — when a Step-1 send fires
  for a re-engagement enrollment, stamp
  ``brand_deal.last_re_engagement_pitch_date`` so M7 Search 1 extends
  the cool-down 50% on the next discovery run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as _date
from typing import Any

from app.repositories.brand_contact import BrandContactRepository
from app.repositories.brand_deal import BrandDealRepository
from app.utils.logging import get_logger

log = get_logger(__name__)


async def append_pitch_history(
    *,
    contact_repo: BrandContactRepository,
    contact_id: str,
    talent_id: str,
    enrollment_id: str,
    template_id: str,
    channel: str = "email",
    pitched_at: datetime | None = None,
) -> None:
    """Append a pitch_history entry to the brand_contact JSONB."""
    when = pitched_at or datetime.now(UTC)
    entry: dict[str, Any] = {
        "talent_id": talent_id,
        "enrollment_id": enrollment_id,
        "template_id": template_id,
        "channel": channel,
        "pitched_at": when.isoformat(),
        "outcome": "in_flight",
    }
    existing = await contact_repo.get_by_id(contact_id)
    if existing is None:
        log.warning(
            "pitch_history_append_skipped_missing_contact",
            contact_id=contact_id,
            enrollment_id=enrollment_id,
        )
        return
    data = dict(existing.data or {})
    history: list[Any] = list(data.get("pitch_history") or [])
    history.append(entry)
    await contact_repo.patch_workflow_state(contact_id, {"pitch_history": history})


async def set_re_engagement_pitch_date(
    *,
    brand_deal_repo: BrandDealRepository,
    talent_id: str,
    brand_id: str,
    fired_at: _date | None = None,
) -> None:
    """Stamp ``brand_deal.last_re_engagement_pitch_date`` for the (talent, brand) pair.

    Looks up the most recent deal for the pair and updates the field.
    Fails-soft (logs + returns) when no historical deal exists — the
    re-engagement angle wouldn't have fired without one, so this is a
    very unexpected state.
    """
    today = fired_at or datetime.now(UTC).date()
    deals = await brand_deal_repo.find_by_talent(talent_id, limit=500)
    target = next(
        (d for d in deals if d.brand_id == brand_id),
        None,
    )
    if target is None:
        log.warning(
            "re_engagement_pitch_date_no_historical_deal",
            talent_id=talent_id,
            brand_id=brand_id,
        )
        return
    data = dict(target.data or {})
    data["last_re_engagement_pitch_date"] = today.isoformat()
    target.data = data
    await brand_deal_repo._session.flush()  # pyright: ignore[reportPrivateUsage]
