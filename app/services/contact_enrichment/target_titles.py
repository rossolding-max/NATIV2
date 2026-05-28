"""Default target-title sets per brand category.

When a caller doesn't supply ``target_titles``, the orchestrator picks
the default set keyed off ``brand.industry_id`` -> coarse category.

These are intentionally small (8-10 titles each). Too wide blows
through the Apollo rate budget; too narrow misses the buyer.
"""

from __future__ import annotations

# Coarse-category buckets keyed by the parent industry. Falls back to
# the consumer-goods set when no match.
_TITLE_SETS: dict[str, list[str]] = {
    "consumer-goods": [
        "Head of Influencer Marketing",
        "Influencer Marketing Manager",
        "VP Marketing",
        "Brand Partnerships Manager",
        "Director of Brand Marketing",
        "Senior Marketing Manager",
        "Head of Social Media",
        "Chief Marketing Officer",
    ],
    "b2b-saas": [
        "VP Marketing",
        "Head of Demand Generation",
        "Head of Growth",
        "Director of Partnerships",
        "Director of Marketing",
        "Head of Brand",
        "Head of Community",
        "Chief Marketing Officer",
    ],
    "agency": [
        "Director of Influencer Marketing",
        "Senior Account Director",
        "Head of Talent Partnerships",
        "Account Manager",
        "Strategy Director",
    ],
    "media-entertainment": [
        "Head of Brand Partnerships",
        "VP Brand Marketing",
        "Head of Influencer",
        "Director of Marketing",
        "Senior Brand Partnerships Manager",
    ],
    "ecommerce": [
        "Head of Influencer Marketing",
        "Head of Growth",
        "VP Marketing",
        "Brand Partnerships Manager",
        "Director of Performance Marketing",
        "Chief Marketing Officer",
    ],
}

# Apollo seniority hints — narrows the search so we don't get junior ICs.
DEFAULT_SENIORITIES: list[str] = ["founder", "c_suite", "vp", "director", "manager"]


def resolve_target_titles(
    *,
    caller_supplied: list[str] | None,
    brand_category: str | None,
) -> list[str]:
    """Pick the target-title set: caller > category default > consumer-goods."""
    if caller_supplied:
        # Dedupe while preserving order.
        return list(dict.fromkeys(t.strip() for t in caller_supplied if t and t.strip()))
    if brand_category and brand_category in _TITLE_SETS:
        return list(_TITLE_SETS[brand_category])
    return list(_TITLE_SETS["consumer-goods"])


def known_categories() -> list[str]:
    """Return the catalog of supported brand categories (for docs / UI)."""
    return sorted(_TITLE_SETS.keys())
