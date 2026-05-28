"""Qualification scoring — positive + negative signals → tier."""

from __future__ import annotations

from app.services.discovery.qualification import qualify_candidate


def test_unit__net_new_brand_no_signals_gets_speculative_tier() -> None:
    score, tier, signals = qualify_candidate(None)
    assert tier == "unqualified"  # 0.10 < 0.30 threshold
    assert score == 0.10
    assert any(s["signal"] == "recent_funding" for s in signals)


def test_unit__macro_brand_with_creator_program_is_qualified() -> None:
    brand = {
        "creator_program_presence": ["direct", "agency_of_record"],
        "typical_campaign_tier": "macro",
        "company_stage": "public",
    }
    score, tier, _ = qualify_candidate(brand)
    # 0.30 (creator program) + 0.20 (macro) + 0.10 (public) = 0.60
    assert score == 0.60
    assert tier == "qualified"


def test_unit__b2b_brand_penalised() -> None:
    brand = {
        "creator_program_presence": ["direct"],
        "typical_campaign_tier": "macro",
        "b2b_vertical": True,
    }
    score, tier, _ = qualify_candidate(brand)
    # 0.30 + 0.20 - 0.20 = 0.30
    assert score == 0.30
    assert tier == "speculative"


def test_unit__micro_tier_penalty() -> None:
    brand = {
        "creator_program_presence": ["direct"],
        "typical_campaign_tier": "micro",
    }
    score, tier, _ = qualify_candidate(brand)
    # 0.30 - 0.15 = 0.15
    assert score == 0.15
    assert tier == "unqualified"


def test_unit__follower_count_boost() -> None:
    brand = {
        "creator_program_presence": ["direct"],
        "typical_campaign_tier": "premium",
        "company_stage": "public",
        "social_handles": {"instagram_followers": 1_000_000},
    }
    score, _, _ = qualify_candidate(brand)
    # 0.30 + 0.20 + 0.10 + 0.05 = 0.65
    assert score == 0.65


def test_unit__low_followers_penalty() -> None:
    brand = {
        "creator_program_presence": ["direct"],
        "social_handles": {"instagram_followers": 10_000},
    }
    score, _, _ = qualify_candidate(brand)
    # 0.30 - 0.10 = 0.20 (float-tolerant)
    assert abs(score - 0.20) < 0.001


def test_unit__signals_present_in_output() -> None:
    brand = {
        "creator_program_presence": ["direct"],
        "company_stage": "series-a",
    }
    _, _, signals = qualify_candidate(brand)
    signal_names = {s["signal"] for s in signals}
    assert "active_creator_program" in signal_names
    assert "recent_funding" in signal_names
