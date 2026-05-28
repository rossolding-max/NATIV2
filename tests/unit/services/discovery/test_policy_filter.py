"""Policy filter — blocked_industries / exclusivities / do_not_recontact / sensitive warnings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from app.services.discovery._models import CandidateSource, QualifiedCandidate
from app.services.discovery.policy_filter import apply_filters


def _make_candidate(brand_id: str, industry_id: str) -> QualifiedCandidate:
    return QualifiedCandidate(
        brand_id=brand_id,
        brand_name=brand_id.title(),
        industry_id=industry_id,
        score=0.5,
        tier="primary",
        sources=[
            CandidateSource(
                brand_id=brand_id,
                brand_name=brand_id.title(),
                industry_id=industry_id,
                search_tag="primary_industry",
                weight=0.5,
            )
        ],
        qualification_score=0.5,
        qualification_tier="qualified",
    )


def _make_taxonomies(sensitive_industries: set[str] | None = None) -> MagicMock:
    sensitive = sensitive_industries or set()
    tax = MagicMock()

    def _check(i: str) -> bool:
        return i in sensitive

    tax.is_sensitive_industry.side_effect = _check
    return tax


def test_unit__blocked_industry_partitioned_to_blocked() -> None:
    candidate = _make_candidate("nike", "sportswear")
    kept, blocked = apply_filters(
        [candidate],
        talent_brand_preferences={"blocked_industries": ["sportswear"]},
        do_not_recontact_brand_ids=set(),
        taxonomies=_make_taxonomies(),
    )
    assert kept == []
    assert len(blocked) == 1
    assert "blocked_industries" in (blocked[0].block_reason or "")


def test_unit__active_exclusivity_blocks() -> None:
    candidate = _make_candidate("nike", "sportswear")
    future = (datetime.now(UTC).date() + timedelta(days=30)).isoformat()
    kept, blocked = apply_filters(
        [candidate],
        talent_brand_preferences={
            "active_exclusivities": [{"industry_id": "sportswear", "ends_on": future}]
        },
        do_not_recontact_brand_ids=set(),
        taxonomies=_make_taxonomies(),
    )
    assert kept == []
    assert "exclusivity" in (blocked[0].block_reason or "")


def test_unit__expired_exclusivity_does_not_block() -> None:
    candidate = _make_candidate("nike", "sportswear")
    past = (datetime.now(UTC).date() - timedelta(days=30)).isoformat()
    kept, blocked = apply_filters(
        [candidate],
        talent_brand_preferences={
            "active_exclusivities": [{"industry_id": "sportswear", "ends_on": past}]
        },
        do_not_recontact_brand_ids=set(),
        taxonomies=_make_taxonomies(),
    )
    assert len(kept) == 1
    assert blocked == []


def test_unit__do_not_recontact_blocks_by_brand_id() -> None:
    candidate = _make_candidate("nike", "sportswear")
    kept, blocked = apply_filters(
        [candidate],
        talent_brand_preferences={},
        do_not_recontact_brand_ids={"nike"},
        taxonomies=_make_taxonomies(),
    )
    assert kept == []
    assert "do_not_recontact" in (blocked[0].block_reason or "")


def test_unit__sensitive_industry_warns_when_not_preferred() -> None:
    candidate = _make_candidate("ladbrokes", "gambling")
    kept, _blocked = apply_filters(
        [candidate],
        talent_brand_preferences={},  # gambling not in preferred_industries
        do_not_recontact_brand_ids=set(),
        taxonomies=_make_taxonomies(sensitive_industries={"gambling"}),
    )
    assert len(kept) == 1
    assert kept[0].warnings
    assert "sensitive" in kept[0].warnings[0]


def test_unit__sensitive_industry_in_preferred_no_warning() -> None:
    candidate = _make_candidate("ladbrokes", "gambling")
    kept, _blocked = apply_filters(
        [candidate],
        talent_brand_preferences={"preferred_industries": ["gambling"]},
        do_not_recontact_brand_ids=set(),
        taxonomies=_make_taxonomies(sensitive_industries={"gambling"}),
    )
    assert kept[0].warnings == []
