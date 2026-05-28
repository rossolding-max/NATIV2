"""Unit tests for the Step 5 questionnaire rule table."""

from __future__ import annotations

from app.services.questionnaire import (
    all_questions,
    build_patch_for_answer,
    next_question,
    static_choices,
)


def test_unit__next_question__empty_data__returns_pronouns_first() -> None:
    q = next_question({})
    assert q is not None
    assert q.field_path == "pronouns"
    assert q.kind == "enum_one"
    assert q.choices_source == "pronouns"


def test_unit__next_question__advances_to_legal_name_after_pronouns() -> None:
    q = next_question({"pronouns": "they/them"})
    assert q is not None
    assert q.field_path == "legal_name"


def test_unit__financial_section_is_last() -> None:
    """commission rate + rate_card come after every other section."""
    data = {
        "pronouns": "she/her",
        "legal_name": "Test Talent Ltd.",
        "gender_identity": "female",
        "bio": "Test bio",
        "date_of_birth": "1990-01-01",
        "career_start_year": 2018,
        "content_niches": ["beauty"],
        "professional_roles": ["creator"],
        "content_pillars": ["GRWM"],
        "languages": ["en"],
        "brand_preferences": {
            "preferred_industries": ["beauty"],
            "blocked_industries": ["gambling"],
            "values_red_lines": ["fur"],
        },
        "contact": {"email": "t@example.com", "phone": "+1"},
    }
    q = next_question(data)
    assert q is not None
    assert q.field_path in {"commission_override.rate", "rate_card"}


def test_unit__agency_level_fields_are_not_asked() -> None:
    """billing_entity / commission_override.model / working_terms.default_usage_rights
    are agency-wide pieces. The talent questionnaire should never surface them."""
    paths = {q.field_path for q in all_questions()}
    assert "billing_entity.legal_name" not in paths
    assert "billing_entity.country" not in paths
    assert "billing_entity.tax_id" not in paths
    assert "commission_override.model" not in paths
    assert "working_terms.default_usage_rights" not in paths


def test_unit__no_help_text_fields_on_question() -> None:
    """The wizard renders only the label — what / why are gone."""
    q = all_questions()[0]
    assert not hasattr(q, "what")
    assert not hasattr(q, "why")


def test_unit__commission_question_is_single_rate_field() -> None:
    """Talent questionnaire keeps only the per-talent target rate;
    the commission MODEL is agency-wide."""
    commission_paths = [q.field_path for q in all_questions() if "commission" in q.field_path]
    assert commission_paths == ["commission_override.rate"]


def test_unit__rate_card_question_kind() -> None:
    rate_card = next(q for q in all_questions() if q.field_path == "rate_card")
    assert rate_card.kind == "rate_card"


def test_unit__pronouns_uses_static_picker_choices() -> None:
    choices = static_choices("pronouns")
    assert choices is not None
    # she/her, he/him, they/them must be present
    values = {v for v, _ in choices}
    assert {"she/her", "he/him", "they/them"} <= values


def test_unit__next_question__all_answered__returns_none() -> None:
    data = {
        "pronouns": "she/her",
        "legal_name": "Test Talent Ltd.",
        "gender_identity": "female",
        "bio": "Test bio",
        "date_of_birth": "1990-01-01",
        "career_start_year": 2018,
        "content_niches": ["beauty"],
        "professional_roles": ["creator"],
        "content_pillars": ["GRWM"],
        "languages": ["en"],
        "brand_preferences": {
            "preferred_industries": ["beauty"],
            "blocked_industries": ["gambling"],
            "values_red_lines": ["fur"],
        },
        "contact": {"email": "t@example.com", "phone": "+1"},
        "commission_override": {"rate": 0.20},
        "rate_card": {"instagram": {"currency": "GBP", "deliverables": {"reel": {"price": 1500}}}},
    }
    assert next_question(data) is None


def test_unit__empty_string_treated_as_unanswered() -> None:
    q = next_question({"pronouns": "  "})
    assert q is not None
    assert q.field_path == "pronouns"


def test_unit__empty_list_treated_as_unanswered() -> None:
    data = {
        "pronouns": "she/her",
        "legal_name": "x",
        "gender_identity": "female",
        "bio": "x",
        "date_of_birth": "1990-01-01",
        "career_start_year": 2018,
        "content_niches": [],
    }
    q = next_question(data)
    assert q is not None
    assert q.field_path == "content_niches"


def test_unit__build_patch_for_answer__nested_path() -> None:
    patch = build_patch_for_answer("brand_preferences.preferred_industries", ["beauty"])
    assert patch == {"brand_preferences": {"preferred_industries": ["beauty"]}}


def test_unit__build_patch_for_answer__top_level() -> None:
    patch = build_patch_for_answer("pronouns", "they/them")
    assert patch == {"pronouns": "they/them"}


def test_unit__enum_questions_declare_choices_source() -> None:
    for q in all_questions():
        if q.kind in {"enum_one", "enum_multi"}:
            assert q.choices_source, f"{q.field_path} enum without choices_source"


def test_unit__static_choices_unknown_key_returns_none() -> None:
    assert static_choices("not-a-real-source") is None
