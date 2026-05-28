"""Search 1 (re-engagement) — cool-down + de-spam logic."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.services.discovery import search_1_reengagement


def _deal(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "brand_id": "gymshark",
        "brand_name": "Gymshark",
        "industry_id": "activewear",
        "ended_at": "2024-01-01",
        "do_not_recontact": False,
    }
    base.update(overrides)
    return base


def test_unit__search_1__eligible_deal_emits_source() -> None:
    sources = search_1_reengagement.run(brand_deals=[_deal()], today=date(2026, 1, 1))
    assert len(sources) == 1
    assert sources[0].search_tag == "previous_brand_reengage"
    assert sources[0].weight == 0.60
    assert sources[0].brand_id == "gymshark"


def test_unit__search_1__do_not_recontact_blocks() -> None:
    sources = search_1_reengagement.run(
        brand_deals=[_deal(do_not_recontact=True)], today=date(2026, 1, 1)
    )
    assert sources == []


def test_unit__search_1__inside_default_cooldown_blocks() -> None:
    """Default cool-down 180d — a deal that ended 60d ago is not eligible."""
    today = date(2026, 1, 1)
    sixty_days_ago = today - timedelta(days=60)
    sources = search_1_reengagement.run(
        brand_deals=[_deal(ended_at=sixty_days_ago.isoformat())], today=today
    )
    assert sources == []


def test_unit__search_1__override_cooldown_respected() -> None:
    today = date(2026, 1, 1)
    sixty_days_ago = today - timedelta(days=60)
    sources = search_1_reengagement.run(
        brand_deals=[_deal(ended_at=sixty_days_ago.isoformat(), cool_down_override_days=30)],
        today=today,
    )
    assert len(sources) == 1


def test_unit__search_1__recent_pitch_extends_cooldown_50pct() -> None:
    """Pitched 10d ago + 180d cool-down → effective 270d; ended 200d ago → blocked."""
    today = date(2026, 1, 1)
    sources = search_1_reengagement.run(
        brand_deals=[
            _deal(
                ended_at=(today - timedelta(days=200)).isoformat(),
                last_re_engagement_pitch_date=(today - timedelta(days=10)).isoformat(),
            )
        ],
        today=today,
    )
    assert sources == []


def test_unit__search_1__old_pitch_does_not_extend_cooldown() -> None:
    """Pitched 60d ago is OUTSIDE the 30d recency window — cool-down stays at 180d."""
    today = date(2026, 1, 1)
    sources = search_1_reengagement.run(
        brand_deals=[
            _deal(
                ended_at=(today - timedelta(days=200)).isoformat(),
                last_re_engagement_pitch_date=(today - timedelta(days=60)).isoformat(),
            )
        ],
        today=today,
    )
    assert len(sources) == 1


def test_unit__search_1__missing_ended_at_skipped() -> None:
    sources = search_1_reengagement.run(brand_deals=[_deal(ended_at=None)], today=date(2026, 1, 1))
    assert sources == []


def test_unit__search_1__missing_brand_id_skipped() -> None:
    sources = search_1_reengagement.run(brand_deals=[_deal(brand_id=None)], today=date(2026, 1, 1))
    assert sources == []
