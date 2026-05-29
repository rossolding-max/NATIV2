"""Orchestrate the M7 brand-discovery pipeline.

``run_discovery`` is the single entry point — load the talent + the
brand-deal history, fan out across the enabled searches, merge their
``CandidateSource`` outputs by ``brand_id``, score + tier them,
qualify, policy-filter, and return a ``DiscoveryRunResult``.

The Celery task at ``app/services/talent_background_research.py`` calls
this (replacing the M5 stub body). REST callers also reach it via the
``POST /api/v1/talents/{id}/brand-discovery/run`` endpoint.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.services.discovery import (
    _industry_softener,
    search_1_reengagement,
    search_2_similar_talent_brands,
    search_3_competitors,
    search_4_competitors_of_similar,
    search_5_7_industry_tiers,
    search_8_parent_sibling_niche,
    search_9_demographic_bridge,
    search_10_geographic,
    search_11_life_stage,
    search_12_complementary_to_exclusivity,
    search_13_values_aligned,
    search_14_2nd_degree_graph,
    search_15_exa_newly_funded,
    search_16_last30days_trending,
    search_17_paid_social_signal,
    search_18_established_brands,
)
from app.services.discovery._geographic_filter import (
    extract_talent_countries,
    filter_sources_by_geo,
)
from app.services.discovery._industry_expansion import (
    expand_past_deal_industries_bidirectionally,
    extract_industries_from_deals,
    extract_industries_from_previous_brands,
)
from app.services.discovery._models import (
    CandidateSource,
    DiscoveryRunResult,
    QualifiedCandidate,
)
from app.services.discovery._seed_map_loader import load_merged_brand_industry_map
from app.services.discovery.catalog import default_enabled_searches
from app.services.discovery.policy_filter import apply_filters
from app.services.discovery.qualification import (
    DEFAULT_QUALIFICATION_THRESHOLD,
    qualify_candidate,
)
from app.utils.logging import get_logger
from app.utils.taxonomies import Taxonomies, get_taxonomies

log = get_logger(__name__)


# Full set sourced from ``catalog.py`` (single source of truth).
# Callers can pass ``enabled_searches=<subset>`` to ``run_discovery`` to
# narrow the run. Search 16 is gated additionally behind
# ``settings.enable_last30days_discovery`` because the skill needs real
# OpenAI + xAI API keys.
DEFAULT_ENABLED_SEARCHES: tuple[str, ...] = default_enabled_searches()

# Score thresholds for tier assignment (when no re-engage tag).
_TIER_THRESHOLDS: list[tuple[float, str]] = [
    (0.50, "primary"),
    (0.25, "secondary"),
    (0.10, "tertiary"),
]


def _new_search_run_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"run_{ts}_{uuid.uuid4().hex[:8]}"


def _load_brand_industry_map(data_dir: Path | None = None) -> dict[str, Any]:
    """Backwards-compat shim — delegates to ``load_merged_brand_industry_map``.

    M7.4 split this into ``_seed_map_loader.load_merged_brand_industry_map``
    so the curated file + auto-grown discovered file get unioned at load
    time. Callers that import this symbol get the merged result.
    """
    return load_merged_brand_industry_map(data_dir)


def _assign_tier(
    *, score: float, tags: set[str]
) -> Literal["re-engage", "primary", "secondary", "tertiary"]:
    if "previous_brand_reengage" in tags:
        return "re-engage"
    for threshold, tier in _TIER_THRESHOLDS:
        if score >= threshold:
            return tier  # type: ignore[return-value]
    # Below the lowest threshold — caller will drop these candidates.
    return "tertiary"


def _merge_sources(
    sources: list[CandidateSource],
) -> dict[str, list[CandidateSource]]:
    """Group sources by ``brand_id``."""
    grouped: dict[str, list[CandidateSource]] = {}
    for src in sources:
        grouped.setdefault(src.brand_id, []).append(src)
    return grouped


def _industries_from_niche_affinity(
    content_niches: list[str],
    taxonomies: Taxonomies,
) -> list[str]:
    """Pull the deterministic primary+secondary affinity industry list.

    Used as the baseline `current_industries` input to the LLM softener
    so the model knows what's already in scope.
    """
    out: list[str] = []
    seen: set[str] = set()
    groups = (taxonomies.niche_industry_affinity or {}).get("groups") or []
    for niche_id in content_niches:
        for group in groups:
            if not isinstance(group, dict) or group.get("niche_id") != niche_id:
                continue
            for tier_key in ("primary", "secondary"):
                for industry_id in group.get(tier_key) or []:
                    if isinstance(industry_id, str) and industry_id not in seen:
                        seen.add(industry_id)
                        out.append(industry_id)
    return out


async def _compute_industry_expansions(
    *,
    talent_data: dict[str, Any],
    brand_deals: list[Any],
    taxonomies: Taxonomies,
) -> tuple[list[str], list[str]]:
    """Return (bidirectional_walk_ids, softener_ids) for downstream wiring.

    Both lists exclude industries already in the deterministic affinity
    walk (no double-emit). The orchestrator merges them and passes the
    combined extras list into S5/6/7 + S15/S18.
    """
    content_niches = [n for n in (talent_data.get("content_niches") or []) if isinstance(n, str)]
    affinity_industries = _industries_from_niche_affinity(content_niches, taxonomies)
    affinity_set = set(affinity_industries)

    # Bidirectional walk from past-deal sub-industries. M7.6 — also
    # include previous_brands industries so talents with past brand
    # history (but no full deal record) still benefit from the walk.
    deal_industries = extract_industries_from_deals(brand_deals)
    previous_brand_industries = extract_industries_from_previous_brands(
        list(talent_data.get("previous_brands") or [])
    )
    combined = list(dict.fromkeys(deal_industries + previous_brand_industries))
    walked = expand_past_deal_industries_bidirectionally(combined, taxonomies)
    walk_extras = [x for x in walked if x not in affinity_set]

    # LLM softener.
    softener_input = affinity_industries + walk_extras
    softener_extras = await _industry_softener.run(
        talent_data=talent_data,
        current_industries=softener_input,
        taxonomies=taxonomies,
    )
    softener_extras = [
        x for x in softener_extras if x not in affinity_set and x not in set(walk_extras)
    ]
    return walk_extras, softener_extras


def _build_exa_industry_seed(
    *,
    all_sources: list[CandidateSource],
    industry_extras: list[str],
) -> list[str]:
    """Return the deduped industry seed for S15 + S18 fan-out.

    Composes:
      1. Industries that surfaced via S5/6 hits (deterministic affinity).
      2. The precomputed extras (bidirectional walk + LLM softener).
    """
    seen: set[str] = set()
    out: list[str] = []
    for src in all_sources:
        if (
            src.search_tag in {"primary_industry", "secondary_industry"}
            and src.industry_id not in seen
        ):
            seen.add(src.industry_id)
            out.append(src.industry_id)
    for industry_id in industry_extras:
        if industry_id not in seen:
            seen.add(industry_id)
            out.append(industry_id)
    return out


async def run_discovery(
    *,
    talent_id: str,
    talent_data: dict[str, Any],
    brand_deals: list[Any],
    enabled_searches: tuple[str, ...] | None = None,
    qualification_threshold: float = DEFAULT_QUALIFICATION_THRESHOLD,  # noqa: ARG001 — kept for v0.1 callers; M7.4 dropped the hard floor in the orchestrator
    taxonomies: Taxonomies | None = None,
    brand_industry_map: dict[str, Any] | None = None,
    today: Any = None,
) -> DiscoveryRunResult:
    """Run the configured searches; return merged + qualified + filtered candidates.

    Service is pure — no DB writes. The Celery task / REST endpoint
    layer does the ``upsert_run_batch`` + ``write_snapshot`` calls.
    """
    enabled = enabled_searches or DEFAULT_ENABLED_SEARCHES
    tax = taxonomies or get_taxonomies()
    bim = brand_industry_map or _load_brand_industry_map()

    content_niches = list(talent_data.get("content_niches") or [])
    previous_brands = list(talent_data.get("previous_brands") or [])
    audience = dict(talent_data.get("audience_demographics") or {})
    brand_preferences = dict(talent_data.get("brand_preferences") or {})

    # M7.4 — compute industry extras BEFORE any search fires so S5 can
    # consume them. One Haiku call (softener) + a deterministic
    # bidirectional walk on past-deal industries.
    _walk_extras, _softener_extras = await _compute_industry_expansions(
        talent_data=talent_data,
        brand_deals=brand_deals,
        taxonomies=tax,
    )
    _industry_extras: list[str] = list(_walk_extras) + list(_softener_extras)

    all_sources: list[CandidateSource] = []
    errors: list[str] = []
    searches_run: list[str] = []

    def _run_safely(name: str, fn: Any) -> None:
        try:
            result = fn()
            if result:
                all_sources.extend(result)
            searches_run.append(name)
        except Exception as exc:
            log.warning("discovery_search_failed", search=name, error=str(exc))
            errors.append(f"{name}: {exc!s}")

    async def _run_safely_async(name: str, coro: Any) -> None:
        try:
            result = await coro
            if result:
                all_sources.extend(result)
            searches_run.append(name)
        except Exception as exc:
            log.warning("discovery_search_failed", search=name, error=str(exc))
            errors.append(f"{name}: {exc!s}")

    if "search_1_reengagement" in enabled:
        _run_safely(
            "search_1_reengagement",
            lambda: search_1_reengagement.run(brand_deals=brand_deals, today=today),
        )
    if "search_2_similar_talent_brands" in enabled:
        _run_safely(
            "search_2_similar_talent_brands",
            lambda: search_2_similar_talent_brands.run(
                similar_talent=list(talent_data.get("similar_talent") or []),
                brand_industry_map=bim,
            ),
        )
    if "search_3_competitors" in enabled:
        _run_safely(
            "search_3_competitors",
            lambda: search_3_competitors.run(
                previous_brands=previous_brands,
                taxonomies=tax,
                brand_industry_map=bim,
            ),
        )
    if "search_4_competitors_of_similar" in enabled:
        _run_safely(
            "search_4_competitors_of_similar",
            lambda: search_4_competitors_of_similar.run(
                similar_talent=list(talent_data.get("similar_talent") or []),
                taxonomies=tax,
                brand_industry_map=bim,
            ),
        )
    if "search_5_primary_industry" in enabled:
        _run_safely(
            "search_5_primary_industry",
            lambda: search_5_7_industry_tiers.run(
                content_niches=content_niches,
                tier="primary",
                taxonomies=tax,
                brand_industry_map=bim,
                extra_target_industries=_industry_extras,
            ),
        )
    if "search_6_secondary_industry" in enabled:
        _run_safely(
            "search_6_secondary_industry",
            lambda: search_5_7_industry_tiers.run(
                content_niches=content_niches,
                tier="secondary",
                taxonomies=tax,
                brand_industry_map=bim,
            ),
        )
    if "search_7_tertiary_industry" in enabled:
        _run_safely(
            "search_7_tertiary_industry",
            lambda: search_5_7_industry_tiers.run(
                content_niches=content_niches,
                tier="tertiary",
                taxonomies=tax,
                brand_industry_map=bim,
            ),
        )
    if "search_8_parent_sibling_niche" in enabled:
        _run_safely(
            "search_8_parent_sibling_niche",
            lambda: search_8_parent_sibling_niche.run(
                content_niches=content_niches,
                taxonomies=tax,
                brand_industry_map=bim,
            ),
        )
    if "search_9_demographic_bridge" in enabled:
        _run_safely(
            "search_9_demographic_bridge",
            lambda: search_9_demographic_bridge.run(
                audience_demographics=audience,
                taxonomies=tax,
                brand_industry_map=bim,
            ),
        )
    if "search_10_geographic" in enabled:
        _run_safely(
            "search_10_geographic",
            lambda: search_10_geographic.run(
                audience_demographics=audience,
                brand_industry_map=bim,
            ),
        )
    if "search_11_life_stage" in enabled:
        _run_safely(
            "search_11_life_stage",
            lambda: search_11_life_stage.run(
                audience_demographics=audience,
                brand_industry_map=bim,
            ),
        )
    if "search_12_complementary_to_exclusivity" in enabled:
        _run_safely(
            "search_12_complementary_to_exclusivity",
            lambda: search_12_complementary_to_exclusivity.run(
                brand_preferences=brand_preferences,
                taxonomies=tax,
                brand_industry_map=bim,
            ),
        )
    if "search_14_2nd_degree_graph" in enabled:
        _run_safely(
            "search_14_2nd_degree_graph",
            lambda: search_14_2nd_degree_graph.run(
                previous_brands=previous_brands,
                taxonomies=tax,
                brand_industry_map=bim,
            ),
        )

    # M7.3 — extract the talent's geo anchor once so Search 15 + 18 can
    # embed it in their Exa queries. Falls back to location.country when
    # audience_demographics is empty (Kevin's case).
    _talent_countries = extract_talent_countries(talent_data)
    _talent_country = _talent_countries[0] if _talent_countries else None

    # M7.4 — derive the fan-out industry list for Exa-driven searches.
    # Combines S5/6 affinity hits (post-search) with the pre-computed
    # bidirectional-walk + LLM-softener extras.
    _exa_industry_seed_full = _build_exa_industry_seed(
        all_sources=all_sources,
        industry_extras=_industry_extras,
    )
    # M7.6 — cap the Exa fan-out to bound cost. S5/6/7/8 (cheap seed-map
    # walks) still see the full industry list; only the Exa-driven
    # S15/S18 are bounded. Ordering preserves affinity hits first, then
    # bidirectional walk, then LLM softener — so the cap keeps the
    # highest-signal industries.
    from app.config import settings as _settings

    _exa_industry_seed = _exa_industry_seed_full[: _settings.discovery_exa_max_industries]
    if len(_exa_industry_seed_full) > len(_exa_industry_seed):
        log.info(
            "discovery_exa_seed_capped",
            full=len(_exa_industry_seed_full),
            used=len(_exa_industry_seed),
            cap=_settings.discovery_exa_max_industries,
        )

    if "search_15_exa_newly_funded" in enabled and _exa_industry_seed:
        await _run_safely_async(
            "search_15_exa_newly_funded",
            search_15_exa_newly_funded.run(
                top_industry_ids=_exa_industry_seed,
                brand_industry_map=bim,
                talent_country=_talent_country,
            ),
        )

    if "search_18_established_brands" in enabled and _exa_industry_seed:
        await _run_safely_async(
            "search_18_established_brands",
            search_18_established_brands.run(
                top_industry_ids=_exa_industry_seed,
                brand_industry_map=bim,
                talent_country=_talent_country,
            ),
        )

    if "search_16_last30days_trending" in enabled:
        # Gated: needs the last30days skill installed + OpenAI/xAI keys.
        from app.config import settings

        if settings.enable_last30days_discovery:
            top_industries_16: list[str] = []
            for src in all_sources:
                if (
                    src.search_tag in {"primary_industry", "secondary_industry"}
                    and src.industry_id not in top_industries_16
                ):
                    top_industries_16.append(src.industry_id)
            if top_industries_16:
                await _run_safely_async(
                    "search_16_last30days_trending",
                    search_16_last30days_trending.run(
                        top_industry_ids=top_industries_16,
                        brand_industry_map=bim,
                    ),
                )

    if "search_17_paid_social_signal" in enabled:
        # M7.2 — gated behind settings.enable_search_17_paid_social inside the
        # search module itself (which also requires a Meta Ad Library token).
        # Reuses the same primary/secondary industry inference as 15+16.
        top_industries_17: list[str] = []
        for src in all_sources:
            if (
                src.search_tag in {"primary_industry", "secondary_industry"}
                and src.industry_id not in top_industries_17
            ):
                top_industries_17.append(src.industry_id)
        if top_industries_17:
            await _run_safely_async(
                "search_17_paid_social_signal",
                search_17_paid_social_signal.run(
                    top_industry_ids=top_industries_17,
                    brand_industry_map=bim,
                ),
            )

    # Runs LAST among LLM searches so it can re-rank the candidate
    # pool that all other searches have surfaced.
    if "search_13_values_aligned" in enabled and all_sources:
        await _run_safely_async(
            "search_13_values_aligned",
            search_13_values_aligned.run(
                brand_preferences=brand_preferences,
                surfaced_sources=list(all_sources),
                brand_industry_map=bim,
            ),
        )

    # Build the seed-map name->entry index once; used by both the geo
    # filter and the per-brand qualification lookup.
    raw_brands: list[Any] = bim.get("brands") or []
    brand_lookup = {
        str(b.get("name", "")).strip().lower(): b for b in raw_brands if isinstance(b, dict)
    }

    # M7.3 — apply the shared geographic filter to the aggregated
    # sources BEFORE merge. Drops brands whose sells_in_countries is an
    # explicit list NOT including any of the talent's countries (Tesco
    # case for US-based Kevin). Net-new (Exa) brands not in the seed
    # map pass through unaltered.
    if _talent_countries:
        all_sources = filter_sources_by_geo(all_sources, brand_lookup, _talent_countries)

    # Merge sources by brand, build qualified candidates.
    grouped = _merge_sources(all_sources)
    qualified: list[QualifiedCandidate] = []
    for brand_id, sources in grouped.items():
        # M7.4 — score is informational metadata only. No drop based on
        # score or tier thresholds; the agent sees every candidate that
        # surfaced from any search and decides what to do with it.
        score = min(1.0, sum(s.weight for s in sources))
        tags = {s.search_tag for s in sources}
        tier = _assign_tier(score=score, tags=tags)
        first_source = sources[0]
        brand_entry = brand_lookup.get(first_source.brand_name.strip().lower())
        # M7.3 — pass tags + notes so the qualifier can promote net-new
        # Exa-discovered brands to "emerging" when LLM confidence >= 0.70.
        q_score, q_tier, signals = qualify_candidate(
            brand_entry,
            source_tags=tags,
            source_notes=[s.note for s in sources],
        )
        # M7.3 — when the brand surfaces only via Exa-discovery tags
        # (recently_funded / established_exa_discovery) AND qualification
        # promoted it to speculative+, override tier="emerging" so the
        # UI distinguishes long-tail net-new brands from the seed-map
        # tier system.
        from app.services.discovery.qualification import EXA_DISCOVERY_TAGS

        if (
            brand_entry is None
            and tags <= EXA_DISCOVERY_TAGS
            and q_tier in {"qualified", "speculative"}
        ):
            tier = "emerging"  # type: ignore[assignment]
        # M7.4 — qualification_threshold is informational. The
        # qualification tier (qualified/speculative/unqualified) is
        # already attached to the candidate; the agent can filter at the
        # REST layer when they want to.
        # M7.5 — aggregate brand-level metadata (domain + social handles)
        # across all S15/S18 sources for this brand. First non-null wins
        # per field; same for each social platform.
        brand_domain: str | None = None
        brand_social: dict[str, str | None] = {
            "instagram": None,
            "tiktok": None,
            "youtube": None,
            "x": None,
            "linkedin": None,
        }
        for s in sources:
            if brand_domain is None and s.brand_domain:
                brand_domain = s.brand_domain
            if s.brand_social_handles:
                for platform, value in s.brand_social_handles.items():
                    if value and brand_social.get(platform) is None:
                        brand_social[platform] = value
        any_social = any(v for v in brand_social.values())
        qualified.append(
            QualifiedCandidate(
                brand_id=brand_id,
                brand_name=first_source.brand_name,
                industry_id=first_source.industry_id,
                score=score,
                tier=tier,
                sources=sources,
                qualification_score=q_score,
                qualification_tier=q_tier,
                qualification_signals=signals,
                domain=brand_domain,
                social_handles=brand_social if any_social else None,
            )
        )

    # do_not_recontact brand_ids from the M6 deal history.
    dnr_brand_ids = {
        str(d.get("brand_id") or "").strip().lower()
        for d in brand_deals
        if isinstance(d, dict) and d.get("do_not_recontact")
    } - {""}

    kept, blocked = apply_filters(
        qualified,
        talent_brand_preferences=brand_preferences,
        do_not_recontact_brand_ids=dnr_brand_ids,
        taxonomies=tax,
    )

    return DiscoveryRunResult(
        talent_id=talent_id,
        search_run_id=_new_search_run_id(),
        generated_at=datetime.now(UTC),
        searches_run=searches_run,
        candidates=kept,
        blocked=blocked,
        errors=errors,
    )
