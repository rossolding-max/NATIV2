"""Unit tests for the Step 5 adaptive-questionnaire rule table."""

from __future__ import annotations

from app.services.questionnaire import build_patch_for_answer, next_question


def test_unit__next_question__empty_data__returns_first() -> None:
    q = next_question({})
    assert q is not None
    assert q.field_path == "pronouns"


def test_unit__next_question__advances_past_answered() -> None:
    data = {"pronouns": "they/them"}
    q = next_question(data)
    assert q is not None
    assert q.field_path == "languages"


def test_unit__next_question__skips_present_required() -> None:
    data = {
        "pronouns": "she/her",
        "languages": ["en"],
        "contact": {"email": "x@y.com"},
        "billing_entity": {
            "legal_name": "X Co",
            "country": "US",
        },
    }
    q = next_question(data)
    assert q is not None
    # Next missing is contact.phone (optional but next in order after billing).
    assert q.field_path != "billing_entity.legal_name"
    assert q.field_path != "contact.email"


def test_unit__next_question__all_answered__returns_none() -> None:
    data = {
        "pronouns": "she/her",
        "languages": ["en"],
        "contact": {"email": "x@y.com", "phone": "+1"},
        "billing_entity": {
            "legal_name": "X Co",
            "country": "US",
            "tax_id": "GB123",
        },
        "working_terms": {"default_usage_rights": "6 months"},
        "brand_preferences": {
            "preferred_industries": ["beauty"],
            "never_work_with": ["gambling"],
        },
        "commission_override": {"rate": 0.20, "model": "agency_invoices_brand_pays_talent_net"},
    }
    assert next_question(data) is None


def test_unit__build_patch_for_answer__nested_path() -> None:
    patch = build_patch_for_answer("billing_entity.legal_name", "Acme Co")
    assert patch == {"billing_entity": {"legal_name": "Acme Co"}}


def test_unit__build_patch_for_answer__top_level() -> None:
    patch = build_patch_for_answer("pronouns", "they/them")
    assert patch == {"pronouns": "they/them"}
