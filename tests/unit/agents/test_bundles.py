"""Unit tests for ``app.agents.bundles`` — no DB required.

Tests the ContextBundle Pydantic model + the static-prefix / dynamic-body
serialisation helpers + the 4 deferred composer NotImplementedError raises.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.agents.bundles import (
    ContextBundle,
    ContextBundleMetadata,
    compose_for_contract,
    compose_for_invoice,
    compose_for_performance_report,
    compose_for_proposal,
)


def _minimal_bundle(**overrides: object) -> ContextBundle:
    """Build a minimal ContextBundle for tests."""
    defaults: dict[str, object] = {
        "metadata": ContextBundleMetadata(
            pack_type="discovery_prep",
            deal_id="deal_test_001",
            agency_id=uuid4(),
            assembled_at=datetime.now(UTC),
        ),
        "talent_profile": {"talent_id": "t_riley", "name": "Riley Carter"},
        "agency_profile": {"agency_id": "a_acme", "name": "Acme"},
        "deal_record": {"deal_id": "deal_test_001", "stage": "lead"},
        "brand_record": {"brand_id": "b_lulu", "name": "Lululemon"},
    }
    defaults.update(overrides)
    return ContextBundle(**defaults)  # type: ignore[arg-type]


def test_unit__bundle_minimal_construction() -> None:
    bundle = _minimal_bundle()
    assert bundle.metadata.pack_type == "discovery_prep"
    assert bundle.metadata.deal_id == "deal_test_001"
    assert bundle.relevant_memos == []
    assert bundle.comparable_brand_deals == []


def test_unit__bundle_static_prefix_includes_4_required_blocks() -> None:
    """Static prefix carries the cacheable portion (talent + agency + brand + deal)."""
    bundle = _minimal_bundle()
    prefix = bundle.static_prefix_text()
    assert "Talent profile" in prefix
    assert "Agency profile" in prefix
    assert "Brand record" in prefix
    assert "Deal record" in prefix
    # Each rendered section should include the actual entity content.
    assert "Riley Carter" in prefix
    assert "Acme" in prefix
    assert "Lululemon" in prefix


def test_unit__bundle_dynamic_body_lists_only_populated_optionals() -> None:
    """Dynamic body skips sections whose entity is None / empty."""
    bundle = _minimal_bundle()
    body = bundle.dynamic_body_text()
    # No optionals set → body is empty.
    assert body == ""

    bundle_with_contact = _minimal_bundle(
        brand_contact={"contact_id": "con_alice", "name": "Alice"}
    )
    body_with_contact = bundle_with_contact.dynamic_body_text()
    assert "Brand contact" in body_with_contact
    assert "Alice" in body_with_contact


def test_unit__bundle_metadata_includes_assembly_provenance() -> None:
    bundle = _minimal_bundle()
    assert bundle.metadata.assembled_by == "deal_orchestrator"
    assert bundle.metadata.assembled_at is not None


@pytest.mark.parametrize(
    ("composer", "milestone"),
    [
        (compose_for_proposal, "M12"),
        (compose_for_contract, "M13"),
        (compose_for_invoice, "M14"),
        (compose_for_performance_report, "M15"),
    ],
)
async def test_unit__deferred_composers_raise_with_milestone_message(
    composer: object, milestone: str
) -> None:
    """The 4 non-M2 composers raise NotImplementedError citing their milestone."""
    with pytest.raises(NotImplementedError, match=milestone):
        await composer()  # type: ignore[operator]
