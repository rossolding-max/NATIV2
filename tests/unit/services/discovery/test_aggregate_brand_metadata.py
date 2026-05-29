"""M7.7+ — Tests for the shared brand-metadata aggregator (domain + social)."""

from __future__ import annotations

from app.services.discovery._models import CandidateSource
from app.services.discovery.orchestrator import _aggregate_brand_metadata


def _src(
    *,
    domain: str | None = None,
    social: dict[str, str | None] | None = None,
    tag: str = "exa_emerging",
) -> CandidateSource:
    return CandidateSource(
        brand_id="x",
        brand_name="X",
        industry_id="toys",
        search_tag=tag,
        weight=0.20,
        note="",
        brand_domain=domain,
        brand_social_handles=social,
    )


def test_unit__aggregate__source_supplies_domain_no_fallback_needed() -> None:
    domain, _social, _any = _aggregate_brand_metadata(
        [_src(domain="brand.com")], brand_entry={"domain": "wrong.com"}
    )
    # Source value wins; entry fallback only kicks in when source is None.
    assert domain == "brand.com"


def test_unit__aggregate__falls_back_to_entry_domain() -> None:
    """When no source supplied a domain, the seed-map entry's domain
    propagates onto the candidate."""
    domain, _, _ = _aggregate_brand_metadata(
        [_src(domain=None)], brand_entry={"domain": "curated.com"}
    )
    assert domain == "curated.com"


def test_unit__aggregate__falls_back_to_entry_social_per_platform() -> None:
    """Each platform falls back independently; mixed sources + entry merge."""
    src = _src(social={"instagram": "@brand", "tiktok": None})
    entry = {
        "social_handles": {
            "instagram": "@wrong",  # source wins
            "tiktok": "@brand_tt",  # fallback kicks in
            "youtube": "@brand_yt",  # fallback kicks in
        }
    }
    _, social, any_social = _aggregate_brand_metadata([src], brand_entry=entry)
    assert social["instagram"] == "@brand"  # source value preserved
    assert social["tiktok"] == "@brand_tt"  # entry fallback
    assert social["youtube"] == "@brand_yt"  # entry fallback
    assert any_social is True


def test_unit__aggregate__no_entry_no_fallback() -> None:
    """When brand_entry is None, only source values populate."""
    domain, social, any_social = _aggregate_brand_metadata(
        [_src(domain=None, social=None)], brand_entry=None
    )
    assert domain is None
    assert all(v is None for v in social.values())
    assert any_social is False


def test_unit__aggregate__first_non_null_source_wins_across_multiple() -> None:
    sources = [
        _src(domain=None),
        _src(domain="first.com"),
        _src(domain="second.com"),
    ]
    domain, _, _ = _aggregate_brand_metadata(sources, brand_entry=None)
    assert domain == "first.com"


def test_unit__aggregate__entry_social_ignored_when_not_dict() -> None:
    domain, social, any_social = _aggregate_brand_metadata(
        [_src(domain=None)], brand_entry={"social_handles": "not a dict"}
    )
    assert domain is None
    assert all(v is None for v in social.values())
    assert any_social is False


def test_unit__aggregate__entry_with_no_relevant_fields_is_safe() -> None:
    domain, social, any_social = _aggregate_brand_metadata(
        [_src(domain="x.com")], brand_entry={"name": "X"}
    )
    assert domain == "x.com"
    assert all(v is None for v in social.values())
    assert any_social is False
