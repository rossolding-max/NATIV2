"""M7.7 Phase 1 — Compile the comprehensive industry universe for a talent.

Composes seven signal sources:

1. Niche affinity (primary/secondary/tertiary tiers from
   ``niche_industry_affinity.json``) — replaces the industry-derivation
   half of S5/6/7.
2. Parent / sibling niche walk — replaces S8's industry derivation.
3. Bidirectional walk on past brand industries (M7.6 helper).
4. Audience-demographic IAB segment overlap — replaces S9's industry
   derivation (``_industry_from_audience``).
5. Life-stage age-band mapping — replaces S11's industry derivation
   (``_industry_from_life_stage``).
6. Exclusivity adjacency — replaces S12's industry derivation
   (``_industry_from_exclusivity``).
7. LLM softener (Haiku call) — augments with industries the deterministic
   table doesn't list (M7.4 helper).

Output: ``list[IndustryProposal]`` with one entry per unique
``industry_id``. When multiple sources surface the same industry, the
highest-priority source's rationale wins (see ``proposal_source_priority``
in ``_models.py``). Lower-priority sources are preserved in
``alternate_rationales`` when the Phase 1.5 review item is constructed.

No cost: in-memory walks + ONE Haiku call for the softener (cap ~$0.001).
"""

from __future__ import annotations

from typing import Any

from app.services.discovery import _industry_softener, _phase_1_relevance_filter
from app.services.discovery._industry_adjacency import adjacent_industries
from app.services.discovery._industry_expansion import (
    expand_past_deal_industries_bidirectionally,
    extract_industries_from_deals,
    extract_industries_from_previous_brands,
)
from app.services.discovery._industry_from_audience import (
    derive_industries_from_audience,
)
from app.services.discovery._industry_from_exclusivity import (
    derive_industries_from_exclusivities,
)
from app.services.discovery._industry_from_life_stage import (
    derive_industries_from_life_stage,
)
from app.services.discovery._models import (
    IndustryProposal,
    proposal_source_priority,
)
from app.utils.taxonomies import Taxonomies


def _niche_affinity_proposals(
    *,
    content_niches: list[str],
    taxonomies: Taxonomies,
) -> list[IndustryProposal]:
    """Walk niche_industry_affinity.json for primary/secondary/tertiary tiers."""
    out: list[IndustryProposal] = []
    groups = (taxonomies.niche_industry_affinity or {}).get("groups") or []
    if not isinstance(groups, list):
        return out
    for niche_id in content_niches:
        for group in groups:
            if not isinstance(group, dict) or group.get("niche_id") != niche_id:
                continue
            for tier_key, source_label in (
                ("primary", "affinity_primary"),
                ("secondary", "affinity_secondary"),
                ("tertiary", "affinity_tertiary"),
            ):
                for industry_id in group.get(tier_key) or []:
                    if not isinstance(industry_id, str):
                        continue
                    rationale = f"Niche affinity ({tier_key}) for niche {niche_id!r}"
                    out.append(
                        IndustryProposal(
                            industry_id=industry_id,
                            rationale=rationale,
                            source=source_label,  # type: ignore[arg-type]
                        )
                    )
    return out


def _parent_sibling_niche_proposals(
    *,
    content_niches: list[str],
    taxonomies: Taxonomies,
) -> list[IndustryProposal]:
    """Walk parent + sibling niches; pull their primary affinity industries."""
    out: list[IndustryProposal] = []
    own_set: set[str] = set(content_niches)
    expansion: set[tuple[str, str]] = set()  # (expanded_niche_id, relation)
    for niche_id in own_set:
        own = taxonomies.get_niche(niche_id)
        if not own:
            continue
        parent = own.get("parent")
        if isinstance(parent, str) and parent:
            expansion.add((parent, "parent"))
            for sibling_id, sibling in taxonomies.niches.items():
                if sibling.get("parent") == parent and sibling_id != niche_id:
                    expansion.add((sibling_id, "sibling"))
    # Drop niches already in the talent's content_niches.
    expansion = {(n, r) for (n, r) in expansion if n not in own_set}
    if not expansion:
        return out
    groups = (taxonomies.niche_industry_affinity or {}).get("groups") or []
    if not isinstance(groups, list):
        return out
    for niche_id, relation in expansion:
        for group in groups:
            if not isinstance(group, dict) or group.get("niche_id") != niche_id:
                continue
            for industry_id in group.get("primary") or []:
                if not isinstance(industry_id, str):
                    continue
                rationale = f"Niche affinity (primary) via {relation} niche {niche_id!r}"
                out.append(
                    IndustryProposal(
                        industry_id=industry_id,
                        rationale=rationale,
                        source="affinity_secondary",
                    )
                )
    return out


def _bidirectional_walk_proposals(
    *,
    brand_deals: list[Any],
    previous_brands: list[Any],
    taxonomies: Taxonomies,
) -> list[IndustryProposal]:
    """For each past brand industry, propose parent + siblings (M7.6 walk)."""
    deal_industries = extract_industries_from_deals(brand_deals)
    prev_industries = extract_industries_from_previous_brands(previous_brands)
    combined = list(dict.fromkeys(deal_industries + prev_industries))
    if not combined:
        return []
    expanded = expand_past_deal_industries_bidirectionally(combined, taxonomies)
    out: list[IndustryProposal] = []
    source_set = set(combined)
    for industry_id in expanded:
        if industry_id in source_set:
            continue  # the original past-brand industry is already proposed by past-brand source
        # Find which past-brand industry surfaced this.
        parent_of_this = taxonomies.get_industry_parent(industry_id)
        if parent_of_this in source_set:
            rationale = (
                f"Bidirectional walk: sibling of past-brand industry "
                f"{parent_of_this!r} (top-level sector {parent_of_this!r})"
            )
        else:
            # Could be a parent of a past-brand industry.
            # Find a child in source_set whose parent equals this industry.
            children_in_source = [
                src for src in source_set if taxonomies.get_industry_parent(src) == industry_id
            ]
            if children_in_source:
                rationale = (
                    f"Bidirectional walk: parent of past-brand industry {children_in_source[0]!r}"
                )
            else:
                rationale = "Bidirectional walk from past brand history"
        out.append(
            IndustryProposal(
                industry_id=industry_id,
                rationale=rationale,
                source="bidirectional_walk",
            )
        )
    # The past-brand industries themselves should also be proposed (they're
    # the seeds for the walk) — tagged competitor_of_previous so the
    # operator sees they're directly worked-in.
    for industry_id in combined:
        out.append(
            IndustryProposal(
                industry_id=industry_id,
                rationale=f"Past brand industry — talent worked with brand(s) in {industry_id!r}",
                source="competitor_of_previous",
            )
        )
    return out


def _similar_talent_walk_proposals(
    *,
    similar_talent: list[Any],
    taxonomies: Taxonomies,
) -> list[IndustryProposal]:
    """For each industry a similar talent worked with, propose the industry
    itself + its parents/siblings via the bidirectional walk.

    Direct similar-talent industries get ``source="similar_talent"`` so the
    operator sees the "this is here because similar talent X worked with
    brand(s) here" rationale. Walked extensions stay under
    ``source="bidirectional_walk"`` but the rationale names the similar
    talent.
    """
    # Flatten similar-talent past brands → (similar_talent_id, industry_id)
    pairs: list[tuple[str, str]] = []
    seen_industries: set[str] = set()
    industry_to_talent: dict[str, str] = {}
    for entry in similar_talent or []:
        if not entry:
            continue
        sim_id = entry.get("talent_id") or entry.get("id") or entry.get("name") or "unknown"
        for pb in entry.get("previous_brands") or []:
            if not pb:
                continue
            industry_id = pb.get("industry_id")
            if not isinstance(industry_id, str) or not industry_id:
                continue
            if industry_id in seen_industries:
                continue
            seen_industries.add(industry_id)
            industry_to_talent[industry_id] = str(sim_id)
            pairs.append((str(sim_id), industry_id))

    if not pairs:
        return []

    out: list[IndustryProposal] = []
    # Direct seeds.
    for sim_id, industry_id in pairs:
        out.append(
            IndustryProposal(
                industry_id=industry_id,
                rationale=(f"Similar talent {sim_id!r} worked with brand(s) in {industry_id!r}"),
                source="similar_talent",
            )
        )

    # Bidirectional walk on similar-talent industries.
    walked = expand_past_deal_industries_bidirectionally(list(seen_industries), taxonomies)
    for industry_id in walked:
        if industry_id in seen_industries:
            continue
        # Identify the similar-talent industry this was walked from.
        parent_of_this = taxonomies.get_industry_parent(industry_id)
        if parent_of_this in seen_industries:
            sim = industry_to_talent.get(str(parent_of_this), "a similar talent")
            rationale = (
                f"Bidirectional walk: sibling of similar talent {sim!r}'s "
                f"industry (under parent {parent_of_this!r})"
            )
        else:
            children_in_source = [
                src for src in seen_industries if taxonomies.get_industry_parent(src) == industry_id
            ]
            if children_in_source:
                sim = industry_to_talent.get(children_in_source[0], "a similar talent")
                rationale = (
                    f"Bidirectional walk: parent of similar talent {sim!r}'s "
                    f"industry {children_in_source[0]!r}"
                )
            else:
                rationale = "Bidirectional walk from similar talent's brand history"
        out.append(
            IndustryProposal(
                industry_id=industry_id,
                rationale=rationale,
                source="bidirectional_walk",
            )
        )
    return out


def _adjacency_proposals(
    *,
    brand_deals: list[Any],
    previous_brands: list[Any],
    similar_talent: list[Any],
) -> list[IndustryProposal]:
    """For each past-brand or similar-talent industry, look up cross-sector
    adjacencies from ``data/industry_adjacency.json`` and emit proposals.

    Adjacencies capture commercial / purchase-intent overlaps that cross
    sectors (hotels ↔ luggage, eyewear ↔ luxury-goods) and aren't covered
    by the taxonomy-driven bidirectional walk.

    Tagged ``source="adjacency"`` with a rationale that names both the
    seed industry and the reason from the adjacency table.
    """
    seed_industries: set[str] = set()
    for industry_id in extract_industries_from_deals(brand_deals):
        seed_industries.add(industry_id)
    for industry_id in extract_industries_from_previous_brands(previous_brands):
        seed_industries.add(industry_id)
    for entry in similar_talent or []:
        if not entry:
            continue
        for pb in entry.get("previous_brands") or []:
            if not pb:
                continue
            industry_id = pb.get("industry_id")
            if isinstance(industry_id, str) and industry_id:
                seed_industries.add(industry_id)

    if not seed_industries:
        return []

    out: list[IndustryProposal] = []
    # Dedup at the (adjacent_industry, seed) level so a single seed maps
    # to one proposal per adjacency.
    emitted: set[tuple[str, str]] = set()
    for seed_industry in seed_industries:
        for adj_industry, reason in adjacent_industries(seed_industry):
            if adj_industry in seed_industries:
                continue  # seed itself is already proposed elsewhere
            key = (adj_industry, seed_industry)
            if key in emitted:
                continue
            emitted.add(key)
            rationale = (
                f"Cross-sector adjacency to past-brand industry {seed_industry!r} ({reason})"
            )
            out.append(
                IndustryProposal(
                    industry_id=adj_industry,
                    rationale=rationale,
                    source="adjacency",
                )
            )
    return out


async def _softener_proposals(
    *,
    talent_data: dict[str, Any],
    current_industries: list[str],
    taxonomies: Taxonomies,
) -> list[IndustryProposal]:
    """One LLM call suggesting industries the deterministic table missed."""
    softener_ids = await _industry_softener.run(
        talent_data=talent_data,
        current_industries=current_industries,
        taxonomies=taxonomies,
    )
    return [
        IndustryProposal(
            industry_id=industry_id,
            rationale="LLM softener suggestion based on talent context",
            source="softener",
        )
        for industry_id in softener_ids
    ]


def _dedup_with_alternates(
    proposals: list[IndustryProposal],
) -> list[tuple[IndustryProposal, list[IndustryProposal]]]:
    """Group proposals by industry_id; return (winner, alternates) pairs.

    Winner = the lowest-priority-number proposal (highest-priority source).
    Alternates = the rest, preserved so the Phase 1.5 UI can show them.
    """
    by_industry: dict[str, list[IndustryProposal]] = {}
    for p in proposals:
        by_industry.setdefault(p.industry_id, []).append(p)
    out: list[tuple[IndustryProposal, list[IndustryProposal]]] = []
    for items in by_industry.values():
        ordered = sorted(items, key=lambda x: proposal_source_priority(x.source))
        winner = ordered[0]
        alternates = ordered[1:]
        out.append((winner, alternates))
    return out


async def compile_industry_universe(
    *,
    talent_data: dict[str, Any],
    brand_deals: list[Any],
    taxonomies: Taxonomies,
) -> tuple[list[tuple[IndustryProposal, list[IndustryProposal]]], list[dict[str, Any]]]:
    """Run all Phase 1 signal sources; return (proposals, removed_by_llm).

    First return: list of (winner, alternates) IndustryProposal pairs.
    Second return: list of dicts ``{industry_id, reason,
    original_source, original_rationale}`` for proposals the M7.7+ LLM
    relevance filter pruned before they reached the operator.

    The relevance filter (Haiku) runs AFTER the deterministic sources
    and BEFORE the softener, so the softener generates its suggestions
    against a clean current-industry list. Affinity + direct past-brand
    + direct similar-talent proposals are protected from filtering.
    """
    content_niches = [n for n in (talent_data.get("content_niches") or []) if isinstance(n, str)]
    previous_brands = list(talent_data.get("previous_brands") or [])
    similar_talent = list(talent_data.get("similar_talent") or [])
    audience_demographics = dict(talent_data.get("audience_demographics") or {})
    brand_preferences = dict(talent_data.get("brand_preferences") or {})

    proposals: list[IndustryProposal] = []
    proposals.extend(
        _niche_affinity_proposals(content_niches=content_niches, taxonomies=taxonomies)
    )
    proposals.extend(
        _parent_sibling_niche_proposals(content_niches=content_niches, taxonomies=taxonomies)
    )
    proposals.extend(
        _bidirectional_walk_proposals(
            brand_deals=brand_deals, previous_brands=previous_brands, taxonomies=taxonomies
        )
    )
    # M7.7+ — similar-talent past brands as additional walk seeds.
    proposals.extend(
        _similar_talent_walk_proposals(similar_talent=similar_talent, taxonomies=taxonomies)
    )
    # M7.7+ — cross-sector adjacency lookup (data/industry_adjacency.json).
    proposals.extend(
        _adjacency_proposals(
            brand_deals=brand_deals,
            previous_brands=previous_brands,
            similar_talent=similar_talent,
        )
    )
    proposals.extend(
        derive_industries_from_audience(
            audience_demographics=audience_demographics, taxonomies=taxonomies
        )
    )
    proposals.extend(derive_industries_from_life_stage(audience_demographics=audience_demographics))
    proposals.extend(
        derive_industries_from_exclusivities(
            brand_preferences=brand_preferences, taxonomies=taxonomies
        )
    )

    # M7.7+ — LLM relevance filter on the deterministic union. Prunes
    # mechanical taxonomy/adjacency noise (e.g. womenswear added to a
    # dad-life male creator) before the softener generates suggestions.
    # Affinity + direct past-brand + direct similar-talent items are
    # protected by the filter; mock-LLM falls open on failure.
    proposals, removed_by_llm = await _phase_1_relevance_filter.filter_irrelevant_proposals(
        proposals, talent_data
    )

    # Softener LAST so it sees the FILTERED current_industries list.
    current_industry_ids = list(dict.fromkeys(p.industry_id for p in proposals))
    proposals.extend(
        await _softener_proposals(
            talent_data=talent_data,
            current_industries=current_industry_ids,
            taxonomies=taxonomies,
        )
    )

    return _dedup_with_alternates(proposals), removed_by_llm
