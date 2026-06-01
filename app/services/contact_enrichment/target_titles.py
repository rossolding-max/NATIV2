"""Default target-title keywords for the contact-enrichment broad capture.

M8 shipped category-keyed dicts (consumer-goods, b2b-saas, agency,
media-entertainment, ecommerce) each with 5-8 hand-curated titles like
"Head of Influencer Marketing", "VP Marketing". That worked but missed
edge cases — a newly-rebranded "Director of Creator Economy" or
"Brand Partnerships Lead" or "Affiliate Manager" wouldn't match any
of the dicts and the relevant person fell through the gap.

M8.1 replaces the category dicts with a single wide keyword list. Apollo
``person_titles`` filter does prefix/substring matching, so "marketing"
catches "VP Marketing", "Director of Brand Marketing", "Influencer
Marketing Manager", "Senior Marketing Manager", etc. With ~12 keywords
covering the marketing-adjacent ecosystem (brand, creator, influencer,
partnerships, social, growth, PR, comms, community, affiliate, plus
founder/CEO for sub-200-person brands) we cast a much wider net at the
same Apollo /people/search cost (search is per-query, not per-record;
broader titles list = same query count).

The downstream filter is the Step 6 ``outreach_recommendation``
classifier — it surfaces "recommended" / "not_recommended" /
"requires_review" so the operator can pick from the broad pool only
the contacts worth paying for email-reveal on.

Callers can still supply a specific ``target_titles`` override (used
by integration tests + advanced agency-operator workflows). When they
don't, the broad keyword list ships.
"""

from __future__ import annotations

# Marketing-adjacent keywords. Apollo /people/search does substring
# matching against `person_titles`, so each entry here catches a family
# of titles (e.g. "marketing" catches every "X Marketing Y" variation).
BROAD_TITLE_KEYWORDS: list[str] = [
    "marketing",
    "brand",
    "creator",
    "influencer",
    "partnerships",
    "social",
    "growth",
    "communications",
    "PR",
    "community",
    "affiliate",
    "founder",
]


# Apollo seniority hints — narrows the search so we don't get every
# junior IC. Kept identical to the M8 list (founder + c_suite + vp +
# director + manager); the Step 6 classifier filters seniority mismatch
# downstream via the outreach_recommendation flag.
DEFAULT_SENIORITIES: list[str] = ["founder", "c_suite", "vp", "director", "manager"]


def resolve_target_titles(
    *,
    caller_supplied: list[str] | None,
    brand_category: str | None = None,  # noqa: ARG001  # back-compat shim; unused in M8.1
) -> list[str]:
    """Pick the target-title keyword list.

    Caller-supplied override wins; otherwise return the broad keyword
    list. The ``brand_category`` arg is retained for back-compat with
    M8 callers but no longer routes to category-specific dicts — the
    broad pool covers every category.
    """
    if caller_supplied:
        return list(dict.fromkeys(t.strip() for t in caller_supplied if t and t.strip()))
    return list(BROAD_TITLE_KEYWORDS)


def known_categories() -> list[str]:
    """Kept for back-compat with callers (catalog endpoint, docs).

    Returns an empty list in M8.1 since category-specific routing no
    longer exists. The single broad list is universal.
    """
    return []
