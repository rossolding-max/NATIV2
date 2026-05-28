"""Policy filtering — applied last, partitions candidates into kept + blocked.

Three layers:
1. ``brand_preferences.blocked_industries[]`` -> hard block per industry
2. ``brand_preferences.active_exclusivities[]`` -> block any candidate in
   the same industry while the exclusivity window is open
3. ``do_not_recontact = True`` on a past deal -> hard block per-brand
4. Sensitive industries (per ``Taxonomies.is_sensitive_industry``) NOT in
   the talent's ``preferred_industries[]`` -> kept, but with a
   ``warning`` attached so the agent can review.

Returns the partitioned ``(kept, blocked)`` lists; the orchestrator
threads warnings through to the QualifiedCandidate.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from app.services.discovery._models import QualifiedCandidate
from app.utils.taxonomies import Taxonomies


def _is_exclusivity_active(exclusivity: dict[str, Any], today: date) -> bool:
    ends = exclusivity.get("ends_on")
    if not ends:
        # No end date = considered active.
        return True
    if isinstance(ends, date):
        return ends >= today
    if isinstance(ends, str):
        try:
            parsed = date.fromisoformat(ends[:10])
        except ValueError:
            return False
        return parsed >= today
    return False


def apply_filters(
    candidates: list[QualifiedCandidate],
    *,
    talent_brand_preferences: dict[str, Any],
    do_not_recontact_brand_ids: set[str],
    taxonomies: Taxonomies,
    today: date | None = None,
) -> tuple[list[QualifiedCandidate], list[QualifiedCandidate]]:
    """Partition candidates into kept + blocked."""
    today_dt = today or datetime.now(UTC).date()

    blocked_industries: set[str] = set()
    raw_blocked = talent_brand_preferences.get("blocked_industries") or []
    if isinstance(raw_blocked, list):
        blocked_industries = {str(i) for i in raw_blocked if isinstance(i, str)}

    preferred_industries: set[str] = set()
    raw_pref = talent_brand_preferences.get("preferred_industries") or []
    if isinstance(raw_pref, list):
        preferred_industries = {str(i) for i in raw_pref if isinstance(i, str)}

    active_exclusivity_industries: set[str] = set()
    raw_excl = talent_brand_preferences.get("active_exclusivities") or []
    if isinstance(raw_excl, list):
        for entry in raw_excl:
            if not isinstance(entry, dict):
                continue
            if _is_exclusivity_active(entry, today_dt):
                industry_id = entry.get("industry_id")
                if isinstance(industry_id, str):
                    active_exclusivity_industries.add(industry_id)

    kept: list[QualifiedCandidate] = []
    blocked: list[QualifiedCandidate] = []
    for candidate in candidates:
        if candidate.brand_id in do_not_recontact_brand_ids:
            candidate.blocked = True
            candidate.block_reason = "do_not_recontact flag on prior deal"
            blocked.append(candidate)
            continue
        if candidate.industry_id in blocked_industries:
            candidate.blocked = True
            candidate.block_reason = f"industry {candidate.industry_id} in blocked_industries"
            blocked.append(candidate)
            continue
        if candidate.industry_id in active_exclusivity_industries:
            candidate.blocked = True
            candidate.block_reason = f"active exclusivity in {candidate.industry_id}"
            blocked.append(candidate)
            continue

        # Sensitive industries: keep but warn (unless the talent explicitly
        # opted into the industry via preferred_industries).
        if (
            taxonomies.is_sensitive_industry(candidate.industry_id)
            and candidate.industry_id not in preferred_industries
        ):
            candidate.warnings.append(
                f"industry {candidate.industry_id} is flagged sensitive; "
                "not in preferred_industries"
            )
        kept.append(candidate)

    return kept, blocked
