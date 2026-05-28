"""Unit tests for the Step-4 reconciliation patch builder."""

from __future__ import annotations

from app.services.talent_reconciliation import (
    ReconciliationDecision,
    build_reconciliation_patch,
)


def test_unit__accept_applies_candidate_value() -> None:
    patch = build_reconciliation_patch(
        [ReconciliationDecision(field_path="bio", action="accept", source_artefact_id="a-1")],
        candidates_by_path={"bio": "An interesting bio."},
    )
    assert patch["bio"] == "An interesting bio."
    prov = patch["extraction_provenance"]["bio"]
    assert prov["action"] == "accept"
    assert prov["value_applied"] == "An interesting bio."
    assert prov["source_artefact_id"] == "a-1"


def test_unit__edit_overrides_candidate_value() -> None:
    patch = build_reconciliation_patch(
        [
            ReconciliationDecision(
                field_path="bio",
                action="edit",
                edited_value="A better bio.",
                source_artefact_id="a-1",
            )
        ],
        candidates_by_path={"bio": "An interesting bio."},
    )
    assert patch["bio"] == "A better bio."
    prov = patch["extraction_provenance"]["bio"]
    assert prov["action"] == "edit"
    assert prov["value_applied"] == "A better bio."
    assert prov["original_candidate"] == "An interesting bio."


def test_unit__reject_writes_no_field_keeps_audit() -> None:
    patch = build_reconciliation_patch(
        [ReconciliationDecision(field_path="bio", action="reject")],
        candidates_by_path={"bio": "An interesting bio."},
    )
    assert "bio" not in patch  # no field written
    prov = patch["extraction_provenance"]["bio"]
    assert prov["action"] == "reject"
    assert prov["original_candidate"] == "An interesting bio."


def test_unit__nested_path_creates_intermediate_dicts() -> None:
    patch = build_reconciliation_patch(
        [
            ReconciliationDecision(
                field_path="audience_demographics.top_countries",
                action="edit",
                edited_value=["US", "UK"],
            )
        ],
        candidates_by_path={},
    )
    assert patch["audience_demographics"]["top_countries"] == ["US", "UK"]


def test_unit__multiple_decisions_merge_into_one_patch() -> None:
    patch = build_reconciliation_patch(
        [
            ReconciliationDecision(field_path="bio", action="accept"),
            ReconciliationDecision(field_path="content_niches", action="accept"),
            ReconciliationDecision(field_path="previous_brands", action="reject"),
        ],
        candidates_by_path={
            "bio": "Bio text",
            "content_niches": ["beauty", "fashion"],
            "previous_brands": [{"brand": "Sephora"}],
        },
    )
    assert patch["bio"] == "Bio text"
    assert patch["content_niches"] == ["beauty", "fashion"]
    assert "previous_brands" not in patch
    assert set(patch["extraction_provenance"].keys()) == {
        "bio",
        "content_niches",
        "previous_brands",
    }


def test_unit__empty_decisions_returns_empty_patch() -> None:
    assert build_reconciliation_patch([], candidates_by_path={}) == {}


def test_unit__accept_with_no_candidate_records_orphan() -> None:
    """If the caller asks to accept but there's no matching candidate,
    the patch contains no field but provenance notes the orphan decision."""
    patch = build_reconciliation_patch(
        [ReconciliationDecision(field_path="bio", action="accept")],
        candidates_by_path={},
    )
    assert "bio" not in patch
    prov = patch["extraction_provenance"]["bio"]
    assert prov["note"] == "accept-with-no-candidate"
