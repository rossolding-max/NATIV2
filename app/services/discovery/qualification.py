"""Qualification scoring — independent layer over the search-weight score.

For each merged candidate, compute a 0-1 ``qualification_score`` based
on positive + negative signals about the brand's likelihood of running
active creator-marketing programs.

Per ``docs/brand_discovery.md`` § "Qualification scoring":
- ``qualified`` (>= 0.60): high-confidence; default include in primary tier
- ``speculative`` (0.30-0.60): include but flag for agent review
- ``unqualified`` (< 0.30): exclude unless explicitly opted in

The threshold for inclusion (default 0.30) is a settings-level constant
in v0.1; per-talent overrides land in M7.1.
"""

from __future__ import annotations

from typing import Any, Literal

# Default inclusion threshold. Candidates with qualification_score below
# this get dropped unless ``include_speculative_below_threshold`` is set.
DEFAULT_QUALIFICATION_THRESHOLD: float = 0.30

# Signal weights — positive boosts, negative penalties.
_SIGNAL_WEIGHTS: dict[str, float] = {
    "active_creator_program": 0.30,
    "macro_or_premium_tier": 0.20,
    "established_company": 0.10,
    "recent_funding": 0.10,
    "observed_creator_partnerships": 0.15,
    "high_brand_follower_count": 0.05,
    # Negative signals
    "micro_or_nano_tier": -0.15,
    "bootstrapped": -0.10,
    "b2b_vertical": -0.20,
    "low_brand_follower_count": -0.10,
}

QualificationTier = Literal["qualified", "speculative", "unqualified"]


def _classify_tier(score: float) -> QualificationTier:
    if score >= 0.60:
        return "qualified"
    if score >= 0.30:
        return "speculative"
    return "unqualified"


def _signal(*, name: str, value: float, detail: str) -> dict[str, Any]:
    return {"signal": name, "weight": value, "details": detail}


_EXA_DISCOVERY_TAGS: set[str] = {"recently_funded", "established_exa_discovery"}
"""Search tags that indicate a candidate came from Exa-driven discovery
rather than the seed map. M7.3 — when these are present alongside a
sufficient LLM confidence, the qualifier promotes net-new brands to
``speculative`` (0.30) instead of the v0.1 default ``unqualified`` (0.10)."""


def _max_llm_confidence_from_notes(notes: list[str]) -> float:
    """Pull the highest ``llm_confidence`` value from CandidateSource notes.

    The discovery searches embed the value into the ``note`` field as
    ``"llm_confidence=0.87"`` so the qualifier doesn't need to depend on
    a richer source data model. Returns 0.0 when no note carries one.
    """
    import re

    best = 0.0
    pattern = re.compile(r"llm_confidence\s*[=:]\s*([01](?:\.\d+)?)")
    for note in notes:
        for match in pattern.finditer(note):
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            if value > best:
                best = value
    return best


def qualify_candidate(
    brand_entry: dict[str, Any] | None,
    *,
    source_tags: set[str] | None = None,
    source_notes: list[str] | None = None,
) -> tuple[float, QualificationTier, list[dict[str, Any]]]:
    """Compute the qualification score for one brand.

    ``brand_entry`` is the row from ``data/brand_industry_map.json`` (or
    None when the brand is net-new from Search 15 / 18 and not yet
    enriched). ``source_tags`` + ``source_notes`` are passed from the
    orchestrator (aggregated across all CandidateSource records joined
    to this brand) so the M7.3 emerging-tier branch can detect Exa-driven
    discovery + LLM confidence. Returns ``(score, tier, signals[])``.
    """
    signals: list[dict[str, Any]] = []
    score = 0.0

    if brand_entry is None:
        # Net-new brand. M7.3: if any source carries an Exa-discovery tag
        # AND LLM confidence >= 0.70, promote to speculative so the
        # brand surfaces by default. Lower confidence / non-Exa origins
        # keep the v0.1 unqualified floor.
        tags = source_tags or set()
        notes = source_notes or []
        confidence = _max_llm_confidence_from_notes(notes)
        if tags & _EXA_DISCOVERY_TAGS and confidence >= 0.70:
            signals.append(
                _signal(
                    name="emerging_exa_discovery",
                    value=0.30,
                    detail=(f"Exa-discovered emerging brand (llm_confidence={confidence:.2f})."),
                )
            )
            return 0.30, _classify_tier(0.30), signals
        signals.append(
            _signal(name="recent_funding", value=0.10, detail="Newly surfaced via Exa discovery.")
        )
        return 0.10, _classify_tier(0.10), signals

    creator_programs = brand_entry.get("creator_program_presence") or []
    if isinstance(creator_programs, list) and creator_programs:
        signals.append(
            _signal(
                name="active_creator_program",
                value=_SIGNAL_WEIGHTS["active_creator_program"],
                detail=f"Programs: {sorted(creator_programs)}.",
            )
        )
        score += _SIGNAL_WEIGHTS["active_creator_program"]

    tier = (brand_entry.get("typical_campaign_tier") or "").strip().lower()
    if tier in {"macro", "premium"}:
        signals.append(
            _signal(
                name="macro_or_premium_tier",
                value=_SIGNAL_WEIGHTS["macro_or_premium_tier"],
                detail=f"typical_campaign_tier={tier}.",
            )
        )
        score += _SIGNAL_WEIGHTS["macro_or_premium_tier"]
    elif tier in {"micro", "nano"}:
        signals.append(
            _signal(
                name="micro_or_nano_tier",
                value=_SIGNAL_WEIGHTS["micro_or_nano_tier"],
                detail=f"typical_campaign_tier={tier}.",
            )
        )
        score += _SIGNAL_WEIGHTS["micro_or_nano_tier"]

    stage = (brand_entry.get("company_stage") or "").strip().lower()
    if stage in {"public", "ipo", "growth", "series-c", "series-d"}:
        signals.append(
            _signal(
                name="established_company",
                value=_SIGNAL_WEIGHTS["established_company"],
                detail=f"company_stage={stage}.",
            )
        )
        score += _SIGNAL_WEIGHTS["established_company"]
    elif stage in {"bootstrapped", "pre-seed"}:
        signals.append(
            _signal(
                name="bootstrapped",
                value=_SIGNAL_WEIGHTS["bootstrapped"],
                detail=f"company_stage={stage}.",
            )
        )
        score += _SIGNAL_WEIGHTS["bootstrapped"]
    elif stage in {"seed", "series-a", "series-b"}:
        signals.append(
            _signal(
                name="recent_funding",
                value=_SIGNAL_WEIGHTS["recent_funding"],
                detail=f"company_stage={stage}.",
            )
        )
        score += _SIGNAL_WEIGHTS["recent_funding"]

    if brand_entry.get("b2b_vertical"):
        signals.append(
            _signal(
                name="b2b_vertical",
                value=_SIGNAL_WEIGHTS["b2b_vertical"],
                detail="Brand serves B2B; creator marketing tends to underperform.",
            )
        )
        score += _SIGNAL_WEIGHTS["b2b_vertical"]

    # Optional follower-count boost (skipped when the field is absent).
    handles = brand_entry.get("social_handles") or {}
    if isinstance(handles, dict) and handles.get("instagram_followers"):
        followers = handles["instagram_followers"]
        if isinstance(followers, int | float):
            if followers >= 500_000:
                signals.append(
                    _signal(
                        name="high_brand_follower_count",
                        value=_SIGNAL_WEIGHTS["high_brand_follower_count"],
                        detail=f"Instagram followers: {int(followers):,}.",
                    )
                )
                score += _SIGNAL_WEIGHTS["high_brand_follower_count"]
            elif followers < 50_000:
                signals.append(
                    _signal(
                        name="low_brand_follower_count",
                        value=_SIGNAL_WEIGHTS["low_brand_follower_count"],
                        detail=f"Instagram followers: {int(followers):,}.",
                    )
                )
                score += _SIGNAL_WEIGHTS["low_brand_follower_count"]

    final = max(0.0, min(1.0, score))
    return final, _classify_tier(final), signals
