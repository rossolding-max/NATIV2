"""Angle filter — trigger evaluation + category preferences + step routing."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.services.outreach import angle_filter


def _angle(
    *,
    angle_id: str,
    category: str,
    trigger_type: str,
    decision_roles: list[str],
    steps: list[int],
    strength: float = 0.5,
    merge_fields_required: list[str] | None = None,
) -> MagicMock:
    a = MagicMock()
    a.angle_id = angle_id
    a.category = category
    a.name = angle_id
    a.authored_strength_score = strength
    a.data = {
        "trigger": {"type": trigger_type},
        "applicable_to_decision_roles": decision_roles,
        "applicable_to_steps": steps,
        "merge_fields_required": merge_fields_required or [],
        "example_phrasing": f"example for {angle_id}",
    }
    return a


def _talent_with_previous_brand(brand: str, industry: str) -> dict[str, Any]:
    return {
        "name": "Jane Talent",
        "previous_brands": [{"brand": brand, "industry_id": industry}],
        "content_niches": ["fitness-training"],
        "similar_talent": [],
        "audience_demographics": {
            "top_countries": ["GB", "US"],
            "gender_split": {"female": 70, "male": 30},
            "interests": ["fitness", "nutrition"],
        },
    }


def test_unit__angle_filter__competitor_trigger_fires_for_matching_industry() -> None:
    talent = _talent_with_previous_brand("Gymshark", "activewear")
    brand = {"name": "Lululemon", "industry_id": "activewear"}
    fires, merge = angle_filter.evaluate_trigger(
        "talent_worked_with_competitor", talent=talent, contact={}, brand=brand
    )
    assert fires is True
    assert merge["competitor_brand"] == "Gymshark"


def test_unit__angle_filter__competitor_trigger_doesnt_fire_for_other_industry() -> None:
    talent = _talent_with_previous_brand("Gymshark", "activewear")
    brand = {"name": "Apple", "industry_id": "consumer-electronics"}
    fires, _ = angle_filter.evaluate_trigger(
        "talent_worked_with_competitor", talent=talent, contact={}, brand=brand
    )
    assert fires is False


def test_unit__angle_filter__unsupported_trigger_fails_soft() -> None:
    fires, merge = angle_filter.evaluate_trigger(
        "talent_upcoming_launch", talent={}, contact={}, brand={}
    )
    assert fires is False
    assert merge == {}


def test_unit__angle_filter__excluded_category_drops_angle() -> None:
    angles = [
        _angle(
            angle_id="comp_proof",
            category="competitive_proof",
            trigger_type="talent_worked_with_competitor",
            decision_roles=["buyer"],
            steps=[1],
        )
    ]
    talent = _talent_with_previous_brand("Gymshark", "activewear")
    out = angle_filter.filter_angles(
        angles=angles,
        talent=talent,
        contact={},
        brand={"name": "Nike", "industry_id": "activewear"},
        step_number=1,
        decision_role="buyer",
        excluded_categories=["competitive_proof"],
    )
    assert out == []


def test_unit__angle_filter__preferred_category_boosts_score() -> None:
    a1 = _angle(
        angle_id="comp_proof",
        category="competitive_proof",
        trigger_type="talent_worked_with_competitor",
        decision_roles=["buyer"],
        steps=[1],
        strength=0.6,
    )
    a2 = _angle(
        angle_id="default",
        category="role_default",
        trigger_type="always_for_buyer",
        decision_roles=["buyer"],
        steps=[1],
        strength=0.6,
    )
    talent = _talent_with_previous_brand("Gymshark", "activewear")
    out = angle_filter.filter_angles(
        angles=[a1, a2],
        talent=talent,
        contact={},
        brand={"name": "Nike", "industry_id": "activewear"},
        step_number=1,
        decision_role="buyer",
        preferred_categories=["competitive_proof"],
    )
    # Both fire; competitive_proof should rank first due to boost.
    assert len(out) == 2
    assert out[0]["angle"].angle_id == "comp_proof"
    assert out[0]["score"] > out[1]["score"]


def test_unit__angle_filter__wrong_step_number_drops_angle() -> None:
    angles = [
        _angle(
            angle_id="step_1_only",
            category="role_default",
            trigger_type="always_for_buyer",
            decision_roles=["buyer"],
            steps=[1],
        )
    ]
    out = angle_filter.filter_angles(
        angles=angles,
        talent={},
        contact={},
        brand={},
        step_number=2,
        decision_role="buyer",
    )
    assert out == []


def test_unit__angle_filter__wrong_role_drops_angle() -> None:
    angles = [
        _angle(
            angle_id="champion_only",
            category="role_default",
            trigger_type="always_for_champion",
            decision_roles=["champion"],
            steps=[1],
        )
    ]
    out = angle_filter.filter_angles(
        angles=angles,
        talent={},
        contact={},
        brand={},
        step_number=1,
        decision_role="buyer",
    )
    assert out == []


def test_unit__angle_filter__similar_talent_trigger() -> None:
    talent = {
        "similar_talent": [
            {
                "name": "Krissy Cela",
                "previous_brands": [{"brand": "Gymshark", "industry_id": "activewear"}],
            }
        ],
        "previous_brands": [],
    }
    fires, merge = angle_filter.evaluate_trigger(
        "similar_talent_partnered_with_brand",
        talent=talent,
        contact={},
        brand={"name": "Gymshark"},
    )
    assert fires is True
    assert merge["similar_talent_name"] == "Krissy Cela"


def test_unit__angle_filter__multiple_similar_talents_trigger() -> None:
    talent = {
        "similar_talent": [
            {
                "name": "Krissy",
                "previous_brands": [{"brand": "Gymshark"}],
            },
            {
                "name": "Whitney",
                "previous_brands": [{"brand": "Gymshark"}],
            },
        ],
    }
    fires, merge = angle_filter.evaluate_trigger(
        "multiple_similar_talents_with_brand",
        talent=talent,
        contact={},
        brand={"name": "Gymshark"},
    )
    assert fires is True
    assert len(merge["similar_talent_names"]) == 2


def test_unit__angle_filter__geo_match_global_brand_fires() -> None:
    talent = {"audience_demographics": {"top_countries": [{"country": "GB"}, {"country": "US"}]}}
    fires, merge = angle_filter.evaluate_trigger(
        "geo_top_country_match",
        talent=talent,
        contact={},
        brand={"hq_country": "FR", "sells_in_countries": "global"},
    )
    assert fires is True
    assert merge["country"] == "GB"  # first top country
