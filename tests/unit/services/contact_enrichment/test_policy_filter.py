"""Policy filter — DNC + per-talent cooldown + qualification threshold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.contact_enrichment import policy_filter
from app.services.contact_enrichment._models import EnrichedContact, QualifiedContact


def _q(
    *,
    contact_id: str = "bc_1",
    score: float = 0.70,
    tier: str = "qualified",
) -> QualifiedContact:
    return QualifiedContact(
        contact=EnrichedContact(contact_id=contact_id, brand_id="gymshark", name="X"),
        qualification_score=score,
        qualification_tier=tier,
        qualification_signals=[],
    )


def test_unit__policy__dnc_blocks_contact() -> None:
    kept, _blocked = policy_filter.apply_contact_filters(
        [_q()],
        existing_workflow={"bc_1": {"do_not_contact": True}},
    )
    assert kept == []
    assert len(_blocked) == 1


def test_unit__policy__below_threshold_blocked() -> None:
    kept, _blocked = policy_filter.apply_contact_filters(
        [_q(score=0.10, tier="unqualified")],
        qualification_threshold=0.30,
    )
    assert kept == []
    assert len(_blocked) == 1


def test_unit__policy__qualified_with_no_existing_state_kept() -> None:
    kept, _blocked = policy_filter.apply_contact_filters([_q(score=0.65)])
    assert len(kept) == 1
    assert _blocked == []


def test_unit__policy__recent_pitch_within_cooldown_blocked() -> None:
    now = datetime.now(UTC)
    workflow = {
        "bc_1": {
            "pitch_history": [
                {
                    "talent_id": "talent-1",
                    "created_at": (now - timedelta(days=3)).isoformat(),
                }
            ]
        }
    }
    kept, _blocked = policy_filter.apply_contact_filters(
        [_q()],
        existing_workflow=workflow,
        talent_id="talent-1",
        cooldown_days=14,
        today=now,
    )
    assert kept == []
    assert len(_blocked) == 1


def test_unit__policy__pitch_older_than_cooldown_allowed() -> None:
    now = datetime.now(UTC)
    workflow = {
        "bc_1": {
            "pitch_history": [
                {
                    "talent_id": "talent-1",
                    "created_at": (now - timedelta(days=30)).isoformat(),
                }
            ]
        }
    }
    kept, _blocked = policy_filter.apply_contact_filters(
        [_q()],
        existing_workflow=workflow,
        talent_id="talent-1",
        today=now,
    )
    assert len(kept) == 1


def test_unit__policy__shared_roster_other_talent_pitch_doesnt_block() -> None:
    """Talent A pitched yesterday; talent B asks today → still pitchable for B."""
    now = datetime.now(UTC)
    workflow = {
        "bc_1": {
            "pitch_history": [
                {
                    "talent_id": "talent-A",
                    "created_at": (now - timedelta(days=1)).isoformat(),
                }
            ]
        }
    }
    kept, _blocked = policy_filter.apply_contact_filters(
        [_q()],
        existing_workflow=workflow,
        talent_id="talent-B",
        today=now,
    )
    assert len(kept) == 1  # B can pitch even though A just did


def test_unit__policy__dnc_outranks_qualification() -> None:
    """A high-qualified DNC contact still gets blocked."""
    kept, _blocked = policy_filter.apply_contact_filters(
        [_q(score=0.99, tier="qualified")],
        existing_workflow={"bc_1": {"do_not_contact": True}},
    )
    assert kept == []
    assert len(_blocked) == 1
