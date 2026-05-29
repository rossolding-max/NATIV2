"""M7.4 — Bidirectional sub-industry walk from past-deal industries.

M7.3 added parent → children walks (Search 5/6/7/8 expand a target
industry into its sub-industries). M7.4 adds the reverse: when a past
deal's industry is a SUB-industry, expand UP to the parent industry
AND across to ALL siblings (other children of the same parent).

Rationale: if a talent has historically worked in `sportswear`,
discovery should also surface brands in `sports-outdoor` (parent) +
`outdoor-gear`, `gym-equipment` (siblings) — the talent has proven
appeal to the broader sector.
"""

from __future__ import annotations

from typing import Any

from app.utils.taxonomies import Taxonomies


def expand_past_deal_industries_bidirectionally(
    deal_industries: list[str],
    taxonomies: Taxonomies,
) -> set[str]:
    """Return the union of past-deal industries with their parents + siblings.

    For each ``industry_id`` in ``deal_industries``:
      - if the industry has a parent (i.e. it's a sub-industry), include
        the parent AND every sub-industry of that parent (siblings, plus
        the original);
      - if the industry has no parent (top-level sector), include just it.

    The original ``industry_id`` is always kept. Dedup is automatic via
    the set return type.
    """
    expanded: set[str] = set()
    for industry_id in deal_industries:
        if not industry_id:
            continue
        expanded.add(industry_id)
        parent = taxonomies.get_industry_parent(industry_id)
        if parent is None:
            continue
        expanded.add(parent)
        for sibling in taxonomies.get_sub_industries(parent):
            expanded.add(sibling)
    return expanded


def extract_industries_from_deals(brand_deals: list[Any]) -> list[str]:
    """Pull deduped industry_ids from brand_deals payload.

    Tolerates dict-shaped deals (``deal.get("industry_id")``) and
    skips entries without an industry.
    """
    out: list[str] = []
    seen: set[str] = set()
    for deal in brand_deals:
        if not isinstance(deal, dict):
            continue
        industry_id = deal.get("industry_id")
        if industry_id and industry_id not in seen:
            out.append(industry_id)
            seen.add(industry_id)
    return out


def extract_industries_from_previous_brands(previous_brands: list[Any]) -> list[str]:
    """M7.6 — pull deduped industry_ids from ``talent.previous_brands[]``.

    Same dict shape as brand_deals (each entry has ``industry_id``).
    Talents typically have past brand relationships without a full deal
    record; this lets the bidirectional walk fire for those brands too.
    """
    out: list[str] = []
    seen: set[str] = set()
    for entry in previous_brands:
        if not isinstance(entry, dict):
            continue
        industry_id = entry.get("industry_id")
        if industry_id and industry_id not in seen:
            out.append(industry_id)
            seen.add(industry_id)
    return out
