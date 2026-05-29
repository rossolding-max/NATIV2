"""Single source of truth for the 16 brand-discovery searches.

Used by:
- ``orchestrator.py`` to derive ``DEFAULT_ENABLED_SEARCHES`` and to
  validate caller-supplied ``enabled_searches`` lists.
- ``app/api/brand_candidates.py`` for the ``GET /brand-discovery/searches``
  catalog endpoint a UI uses to render the picker.

Adding or removing a search means updating this list (one place) plus
wiring the dispatch in ``orchestrator.run_discovery``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchInfo:
    """Metadata for one of the 16 Phase-2 brand-discovery searches."""

    name: str
    label: str
    description: str
    weight: str  # human-readable weight string (e.g. "0.60", "0.10-0.20")
    requires_llm: bool = False
    requires_external_skill: bool = False


SEARCH_CATALOG: tuple[SearchInfo, ...] = (
    SearchInfo(
        name="search_1_reengagement",
        label="Previous-brand re-engagement",
        description=(
            "Surface brands the talent has worked with before, now past the cool-down window."
        ),
        weight="0.60",
    ),
    SearchInfo(
        name="search_2_similar_talent_brands",
        label="Similar-talent brands",
        description=(
            "Walk talent.similar_talent[].previous_brands[]; weight scales with mention count."
        ),
        weight="0.10-0.20",
    ),
    SearchInfo(
        name="search_3_competitors",
        label="Competitors of previous brands",
        description=(
            "Direct competitors of brands the talent has worked with (via brand_competitors.json)."
        ),
        weight="0.25",
    ),
    SearchInfo(
        name="search_4_competitors_of_similar",
        label="Competitors of similar-talent brands",
        description="Brands that compete with the brands worked with by similar talents.",
        weight="0.10",
    ),
    SearchInfo(
        name="search_5_primary_industry",
        label="Primary industries from niches",
        description="Brands in the talent's primary-tier niche -> industry affinity matches.",
        weight="0.30",
    ),
    SearchInfo(
        name="search_6_secondary_industry",
        label="Secondary industries from niches",
        description="Brands in the talent's secondary-tier niche -> industry affinity matches.",
        weight="0.20",
    ),
    SearchInfo(
        name="search_7_tertiary_industry",
        label="Tertiary industries from niches",
        description="Brands in the talent's tertiary-tier niche -> industry affinity matches.",
        weight="0.06",
    ),
    SearchInfo(
        name="search_8_parent_sibling_niche",
        label="Parent + sibling niches",
        description=(
            "Climb the niche taxonomy to the parent + siblings; pull their primary industries."
        ),
        weight="0.08",
    ),
    SearchInfo(
        name="search_9_demographic_bridge",
        label="Demographic bridge (IAB segments)",
        description=(
            "Brands in industries whose IAB audience segments overlap the talent's audience."
        ),
        weight="0.15-0.25",
    ),
    SearchInfo(
        name="search_10_geographic",
        label="Geographic alignment",
        description=(
            "Brands whose HQ or sells-in markets match the talent's top audience countries."
        ),
        weight="0.04-0.08",
    ),
    SearchInfo(
        name="search_11_life_stage",
        label="Audience life-stage",
        description="Industries aligned to the dominant audience age band (IAB-derived).",
        weight="0.04",
    ),
    SearchInfo(
        name="search_12_complementary_to_exclusivity",
        label="Complementary to active exclusivities",
        description=(
            "Adjacent industries around active exclusivities "
            "(parent + siblings, NOT the locked one)."
        ),
        weight="0.05",
    ),
    SearchInfo(
        name="search_13_values_aligned",
        label="Values-aligned (LLM)",
        description=(
            "One Claude call per run; classifies top-50 surfaced brands against talent values."
        ),
        weight="0.05",
        requires_llm=True,
    ),
    SearchInfo(
        name="search_14_2nd_degree_graph",
        label="2nd-degree competitor graph",
        description=(
            "Competitors-of-competitors; excludes 1st-hop set so it "
            "doesn't double-count Search 3/4."
        ),
        weight="0.03",
    ),
    SearchInfo(
        name="search_15_exa_newly_funded",
        label="Newly-funded brands (Exa + LLM)",
        description=(
            "Exa-driven discovery of net-new brands recently funded "
            "inside the talent's top industries."
        ),
        weight="0.10-0.15",
        requires_llm=True,
    ),
    SearchInfo(
        name="search_16_last30days_trending",
        label="Trending brands (last 30 days)",
        description=(
            "Wraps the last30days skill; mines Reddit + X chatter for "
            "brand mentions in the talent's industries."
        ),
        weight="0.06",
        requires_external_skill=True,
    ),
    SearchInfo(
        name="search_17_paid_social_signal",
        label="Brands spending heavily on paid social",
        description=(
            "Active ads in last 30 days on Meta Ad Library + TikTok "
            "Creative Center. Multi-platform brands score higher."
        ),
        weight="0.20-0.30",
    ),
)


KNOWN_SEARCH_NAMES: frozenset[str] = frozenset(s.name for s in SEARCH_CATALOG)


def default_enabled_searches() -> tuple[str, ...]:
    """The full set of search names, in canonical order."""
    return tuple(s.name for s in SEARCH_CATALOG)


def validate_search_names(names: list[str]) -> list[str]:
    """Return the subset of ``names`` not present in the catalog (i.e. unknown).

    The caller decides what to do with unknown names — typically a 422.
    """
    return [n for n in names if n not in KNOWN_SEARCH_NAMES]
