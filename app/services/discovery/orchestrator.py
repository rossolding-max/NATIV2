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

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from app.services.discovery import (
    search_1_reengagement,
    search_3_competitors,
    search_5_7_industry_tiers,
    search_9_demographic_bridge,
    search_10_geographic,
)
from app.services.discovery._models import (
    CandidateSource,
    DiscoveryRunResult,
    QualifiedCandidate,
)
from app.services.discovery.policy_filter import apply_filters
from app.services.discovery.qualification import (
    DEFAULT_QUALIFICATION_THRESHOLD,
    qualify_candidate,
)
from app.utils.logging import get_logger
from app.utils.taxonomies import Taxonomies, get_taxonomies

log = get_logger(__name__)


# Searches shipped in the v0.1 M7 Core 8 subset. Search 15 (Exa-driven)
# lands in Commit 2; the deterministic 7 below run in Commit 1.
DEFAULT_ENABLED_SEARCHES: tuple[str, ...] = (
    "search_1_reengagement",
    "search_3_competitors",
    "search_5_primary_industry",
    "search_6_secondary_industry",
    "search_7_tertiary_industry",
    "search_9_demographic_bridge",
    "search_10_geographic",
)

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
    repo_root = Path(__file__).resolve().parents[3]
    path = (data_dir or repo_root / "data") / "brand_industry_map.json"
    if not path.exists():
        return {"brands": []}
    return json.loads(path.read_text(encoding="utf-8"))


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


async def run_discovery(
    *,
    talent_id: str,
    talent_data: dict[str, Any],
    brand_deals: list[Any],
    enabled_searches: tuple[str, ...] | None = None,
    qualification_threshold: float = DEFAULT_QUALIFICATION_THRESHOLD,
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

    if "search_1_reengagement" in enabled:
        _run_safely(
            "search_1_reengagement",
            lambda: search_1_reengagement.run(brand_deals=brand_deals, today=today),
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
    if "search_5_primary_industry" in enabled:
        _run_safely(
            "search_5_primary_industry",
            lambda: search_5_7_industry_tiers.run(
                content_niches=content_niches,
                tier="primary",
                taxonomies=tax,
                brand_industry_map=bim,
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

    # Merge sources by brand, build qualified candidates.
    grouped = _merge_sources(all_sources)
    raw_brands: list[Any] = bim.get("brands") or []
    brand_lookup = {
        str(b.get("name", "")).strip().lower(): b for b in raw_brands if isinstance(b, dict)
    }
    qualified: list[QualifiedCandidate] = []
    for brand_id, sources in grouped.items():
        score = min(1.0, sum(s.weight for s in sources))
        if score < _TIER_THRESHOLDS[-1][0]:
            continue  # below the lowest tier threshold
        tags = {s.search_tag for s in sources}
        tier = _assign_tier(score=score, tags=tags)
        first_source = sources[0]
        brand_entry = brand_lookup.get(first_source.brand_name.strip().lower())
        q_score, q_tier, signals = qualify_candidate(brand_entry)
        if q_score < qualification_threshold:
            continue  # dropped by qualification floor
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
