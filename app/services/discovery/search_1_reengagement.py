"""Search 1 — re-engagement of previous brands.

Reads M6 ``brand_deal`` rows for the talent, computes per-deal
``renewal_eligibility_date = ended_at + (cool_down_override_days OR 180)``,
filters ``do_not_recontact = True`` permanently, and extends the
cool-down 50% when ``last_re_engagement_pitch_date`` is recent and no
response signal yet (anti-spam de-spam).

Outputs a ``CandidateSource`` per eligible past brand with the highest
weight in the discovery stack (0.60) — these are warmest signals
because the agency has a working relationship with the brand.
"""

from __future__ import annotations

from datetime import UTC, date, timedelta
from typing import Any

from app.services.discovery._models import CandidateSource

# Defaults — overridable per-deal via ``cool_down_override_days``.
_DEFAULT_COOL_DOWN_DAYS: int = 180
# Recency window for the anti-spam de-spam check. If the talent was
# pitched a re-engagement within this many days AND there's no positive
# response yet (M9 writes the response signal), extend the cool-down 50%.
_RECENT_PITCH_WINDOW_DAYS: int = 30
_DE_SPAM_MULTIPLIER: float = 1.5


def _coerce_date(value: Any) -> date | None:
    """Best-effort date coercion (handles ISO strings + actual ``date``)."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _compute_effective_cool_down(
    *,
    cool_down_override_days: Any,
    last_re_engagement_pitch_date: date | None,
    today: date,
) -> int:
    """Return the cool-down in days, extended 50% if the talent pitched recently."""
    base = (
        int(cool_down_override_days)
        if isinstance(cool_down_override_days, int | float) and cool_down_override_days > 0
        else _DEFAULT_COOL_DOWN_DAYS
    )
    if last_re_engagement_pitch_date is not None:
        delta = today - last_re_engagement_pitch_date
        if 0 <= delta.days <= _RECENT_PITCH_WINDOW_DAYS:
            return int(base * _DE_SPAM_MULTIPLIER)
    return base


def run(
    *,
    brand_deals: list[Any],
    today: date | None = None,
) -> list[CandidateSource]:
    """Surface eligible past brands as re-engagement candidates.

    ``brand_deals`` is a list of dicts mirroring the ``brand_deal.data``
    JSONB payload (the orchestrator pulls these from the BrandDealRepository
    + flattens for the search modules).
    """
    today = today or _today()
    sources: list[CandidateSource] = []
    for deal in brand_deals:
        if not isinstance(deal, dict):
            continue
        if deal.get("do_not_recontact"):
            continue
        ended_at = _coerce_date(deal.get("ended_at"))
        if ended_at is None:
            # Still active — not eligible for re-engagement yet.
            continue
        last_pitch = _coerce_date(deal.get("last_re_engagement_pitch_date"))
        effective_days = _compute_effective_cool_down(
            cool_down_override_days=deal.get("cool_down_override_days"),
            last_re_engagement_pitch_date=last_pitch,
            today=today,
        )
        renewal_date = ended_at + timedelta(days=effective_days)
        if today < renewal_date:
            continue  # still in cool-down
        brand_id = str(deal.get("brand_id") or "").strip().lower()
        brand_name = str(deal.get("brand_name") or deal.get("brand") or brand_id)
        industry_id = str(deal.get("industry_id") or "")
        if not brand_id or not industry_id:
            continue
        note = (
            f"Past deal ended {ended_at.isoformat()}; "
            f"renewal-eligible since {renewal_date.isoformat()}."
        )
        sources.append(
            CandidateSource(
                brand_id=brand_id,
                brand_name=brand_name,
                industry_id=industry_id,
                search_tag="previous_brand_reengage",
                weight=0.60,
                note=note,
            )
        )
    return sources


def _today() -> date:
    from datetime import datetime

    return datetime.now(UTC).date()
