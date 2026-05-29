"""Qualification emerging-tier branch (M7.3)."""

from __future__ import annotations

from app.services.discovery.qualification import qualify_candidate


def test_unit__qual_emerging__net_new_with_exa_tag_and_high_confidence_promotes() -> None:
    """Search 15 / Search 18 net-new brand with LLM confidence >= 0.70 ->
    speculative (0.30) instead of unqualified (0.10)."""
    score, tier, signals = qualify_candidate(
        None,
        source_tags={"recently_funded"},
        source_notes=["llm_confidence=0.87 evidence=...startup raised Series A..."],
    )
    assert score == 0.30
    assert tier == "speculative"
    assert any(s["signal"] == "emerging_exa_discovery" for s in signals)


def test_unit__qual_emerging__established_exa_tag_promotes() -> None:
    """Search 18's established_exa_discovery tag also promotes when conf high."""
    score, tier, _ = qualify_candidate(
        None,
        source_tags={"established_exa_discovery"},
        source_notes=["llm_confidence=0.92"],
    )
    assert score == 0.30
    assert tier == "speculative"


def test_unit__qual_emerging__low_confidence_stays_unqualified() -> None:
    """LLM confidence below 0.70 -> v0.1 unqualified path preserved."""
    score, tier, _ = qualify_candidate(
        None,
        source_tags={"recently_funded"},
        source_notes=["llm_confidence=0.55"],
    )
    assert score == 0.10
    assert tier == "unqualified"


def test_unit__qual_emerging__no_exa_tag_stays_unqualified() -> None:
    """Net-new brand without an Exa-discovery tag uses the v0.1 path."""
    score, tier, _ = qualify_candidate(
        None,
        source_tags={"primary_industry"},  # non-Exa origin
        source_notes=["llm_confidence=0.95"],
    )
    assert score == 0.10
    assert tier == "unqualified"


def test_unit__qual_emerging__missing_kwargs_preserves_old_signature() -> None:
    """Existing callers passing only brand_entry continue to work."""
    score, tier, _ = qualify_candidate(None)
    assert score == 0.10
    assert tier == "unqualified"


def test_unit__qual_emerging__seed_map_brand_uses_full_signal_path() -> None:
    """Brand IS in seed map -> standard qualification ignores the Exa flag."""
    brand_entry = {
        "name": "Nike",
        "industry_id": "sportswear",
        "creator_program_presence": ["direct"],
        "typical_campaign_tier": "premium",
        "company_stage": "public",
    }
    score, tier, signals = qualify_candidate(
        brand_entry,
        source_tags={"recently_funded"},
        source_notes=["llm_confidence=0.90"],
    )
    # Standard signal-sum path (no emerging signal — brand is established).
    assert score > 0.40
    assert tier == "qualified"
    assert not any(s["signal"] == "emerging_exa_discovery" for s in signals)


def test_unit__qual_emerging__confidence_picks_highest_across_notes() -> None:
    """When multiple source notes carry different confidences, max wins."""
    score, _, _ = qualify_candidate(
        None,
        source_tags={"recently_funded"},
        source_notes=[
            "llm_confidence=0.62 first source",
            "llm_confidence=0.78 second source — better",
        ],
    )
    assert score == 0.30  # 0.78 >= 0.70 -> promoted
