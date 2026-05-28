"""Per-contact qualification scoring."""

from __future__ import annotations

import pytest

from app.services.contact_enrichment import qualification
from app.services.contact_enrichment._models import EnrichedContact


def _contact(
    *,
    decision_role: str = "unknown",
    title: str | None = "VP Marketing",
    seniority: str | None = "vp",
    email_status: str | None = None,
) -> EnrichedContact:
    return EnrichedContact(
        contact_id="bc_x",
        brand_id="gymshark",
        name="X",
        title=title,
        seniority=seniority,
        decision_role=decision_role,
        email_verification_status=email_status,
    )


def test_unit__qualification__buyer_senior_marketing_with_verified_email_qualifies() -> None:
    out = qualification.qualify_contact(
        _contact(
            decision_role="buyer",
            title="VP Marketing",
            seniority="vp",
            email_status="verified",
        )
    )
    # 0.30 + 0.20 + 0.20 + 0.10 = 0.80 (float rounding ~ 0.7999...)
    assert out.qualification_score == pytest.approx(0.80)
    assert out.qualification_tier == "qualified"


def test_unit__qualification__gatekeeper_only_penalised() -> None:
    out = qualification.qualify_contact(
        _contact(
            decision_role="gatekeeper",
            title="Executive Assistant",
            seniority="manager",
        )
    )
    # -0.10 + 0 + 0 = -0.10 clamped to 0.0
    assert out.qualification_score == 0.0
    assert out.qualification_tier == "unqualified"


def test_unit__qualification__champion_treated_as_positive() -> None:
    out = qualification.qualify_contact(
        _contact(
            decision_role="champion",
            title="Influencer Marketing Manager",
            seniority="manager",
        )
    )
    # 0.20 (champion) + 0.20 (marketing keyword) = 0.40 — speculative
    assert out.qualification_score == pytest.approx(0.40)
    assert out.qualification_tier == "speculative"


def test_unit__qualification__no_signals_unqualified() -> None:
    out = qualification.qualify_contact(
        _contact(
            decision_role="unknown",
            title="Operations Analyst",
            seniority="ic",
        )
    )
    assert out.qualification_score == 0.0
    assert out.qualification_tier == "unqualified"


def test_unit__qualification__signals_recorded_with_weights() -> None:
    out = qualification.qualify_contact(
        _contact(
            decision_role="buyer",
            title="VP Marketing",
            seniority="vp",
        )
    )
    names = {s["signal"] for s in out.qualification_signals}
    assert "buyer_decision_role" in names
    assert "senior_seniority" in names
    assert "marketing_function" in names


def test_unit__qualification__score_clamped_to_one() -> None:
    """Even with every positive signal, score caps at 1.0."""
    out = qualification.qualify_contact(
        _contact(
            decision_role="buyer",
            title="Head of Influencer Marketing",
            seniority="founder",
            email_status="verified",
        )
    )
    assert 0.0 <= out.qualification_score <= 1.0
