"""Filter the angle library for one step of one enrollment.

For each angle in the library, evaluate its ``trigger.type`` against
the (talent, contact, brand) context. Angles that fire AND apply to
the contact's ``decision_role`` AND apply to this step number become
candidates. v0.1 implements a pragmatic subset of the 40 trigger
types; the rest fail-soft to ``False``.

See ``schemas/pitch_angle.schema.json`` for the full enum.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.models.sqla.pitch_angle import PitchAngle

# v0.1 implements the high-signal triggers below. Others return
# (False, {}) — the angle is silently skipped. Each additional trigger
# is a small follow-up PR (one function per trigger).
_SUPPORTED_TRIGGERS: frozenset[str] = frozenset(
    {
        "talent_worked_with_competitor",
        "talent_worked_in_same_industry",
        "similar_talent_partnered_with_brand",
        "multiple_similar_talents_with_brand",
        "niche_primary_affinity",
        "iab_demographic_overlap",
        "gender_skew_match",
        "geo_top_country_match",
        "past_brand_eligible_reengagement",
        "always_for_buyer",
        "always_for_influencer",
        "always_for_gatekeeper",
        "always_for_champion",
    }
)


def _competitor_brands(talent: dict[str, Any]) -> set[str]:
    """Names from ``talent.previous_brands[].brand`` lowercased."""
    out: set[str] = set()
    for entry in talent.get("previous_brands") or []:
        if isinstance(entry, dict):
            name = entry.get("brand") or entry.get("name")
            if isinstance(name, str):
                out.add(name.strip().lower())
    return out


def _eval_talent_worked_with_competitor(
    *, talent: dict[str, Any], brand: dict[str, Any], **_: Any
) -> tuple[bool, dict[str, Any]]:
    """Fires when the talent has a deal with a brand in the same industry."""
    target_industry = (brand.get("industry_id") or "").strip().lower()
    if not target_industry:
        return False, {}
    for entry in talent.get("previous_brands") or []:
        if not isinstance(entry, dict):
            continue
        if (entry.get("industry_id") or "").strip().lower() == target_industry:
            return True, {
                "competitor_brand": entry.get("brand") or entry.get("name"),
                "industry_id": target_industry,
            }
    return False, {}


def _eval_talent_worked_in_same_industry(
    *, talent: dict[str, Any], brand: dict[str, Any], **_: Any
) -> tuple[bool, dict[str, Any]]:
    return _eval_talent_worked_with_competitor(talent=talent, brand=brand)


def _eval_similar_talent_partnered_with_brand(
    *, talent: dict[str, Any], brand: dict[str, Any], **_: Any
) -> tuple[bool, dict[str, Any]]:
    brand_key = (brand.get("name") or "").strip().lower()
    if not brand_key:
        return False, {}
    for sim in talent.get("similar_talent") or []:
        if not isinstance(sim, dict):
            continue
        for past in sim.get("previous_brands") or []:
            if not isinstance(past, dict):
                continue
            name = (past.get("brand") or past.get("name") or "").strip().lower()
            if name == brand_key:
                return True, {
                    "similar_talent_name": sim.get("name"),
                    "brand_name": brand.get("name"),
                }
    return False, {}


def _eval_multiple_similar_talents_with_brand(
    *, talent: dict[str, Any], brand: dict[str, Any], **_: Any
) -> tuple[bool, dict[str, Any]]:
    brand_key = (brand.get("name") or "").strip().lower()
    if not brand_key:
        return False, {}
    matches: list[str] = []
    for sim in talent.get("similar_talent") or []:
        if not isinstance(sim, dict):
            continue
        for past in sim.get("previous_brands") or []:
            if not isinstance(past, dict):
                continue
            if (past.get("brand") or past.get("name") or "").strip().lower() == brand_key:
                name = sim.get("name")
                if isinstance(name, str):
                    matches.append(name)
                break
    if len(matches) >= 2:
        return True, {"similar_talent_names": matches, "brand_name": brand.get("name")}
    return False, {}


def _eval_niche_primary_affinity(
    *, talent: dict[str, Any], brand: dict[str, Any], **_: Any
) -> tuple[bool, dict[str, Any]]:
    talent_niches = {n for n in (talent.get("content_niches") or []) if isinstance(n, str)}
    if not talent_niches:
        return False, {}
    brand_niches = {n for n in (brand.get("primary_niche_ids") or []) if isinstance(n, str)}
    overlap = talent_niches & brand_niches
    if overlap:
        return True, {"niche_ids": sorted(overlap)}
    # Soft signal: brand industry matches at least one of the talent's niches
    # (covers brands without explicit primary_niche_ids).
    industry_id = (brand.get("industry_id") or "").strip().lower()
    if industry_id and any(industry_id in n for n in talent_niches):
        return True, {"industry_id": industry_id}
    return False, {}


def _eval_iab_demographic_overlap(
    *, talent: dict[str, Any], brand: dict[str, Any], **_: Any
) -> tuple[bool, dict[str, Any]]:
    talent_segments = {
        s
        for s in (talent.get("audience_demographics") or {}).get("interests") or []
        if isinstance(s, str)
    }
    if not talent_segments:
        return False, {}
    brand_segments = {s for s in (brand.get("audience_segments") or []) if isinstance(s, str)}
    overlap = talent_segments & brand_segments
    if overlap:
        return True, {"segments": sorted(overlap)}
    return False, {}


def _eval_gender_skew_match(
    *, talent: dict[str, Any], brand: dict[str, Any], **_: Any
) -> tuple[bool, dict[str, Any]]:
    split = (talent.get("audience_demographics") or {}).get("gender_split") or {}
    if not isinstance(split, dict):
        return False, {}
    female = split.get("female") or 0
    male = split.get("male") or 0
    if not (isinstance(female, int | float) and isinstance(male, int | float)):
        return False, {}
    skew = "female" if female > male + 10 else ("male" if male > female + 10 else None)
    if not skew:
        return False, {}
    brand_target = (brand.get("primary_audience_gender") or "").strip().lower()
    if brand_target == skew:
        return True, {"gender_skew": skew, "share": max(female, male)}
    return False, {}


def _eval_geo_top_country_match(
    *, talent: dict[str, Any], brand: dict[str, Any], **_: Any
) -> tuple[bool, dict[str, Any]]:
    countries: list[str] = []
    for c in (talent.get("audience_demographics") or {}).get("top_countries") or []:
        if isinstance(c, str):
            countries.append(c)
        elif isinstance(c, dict) and isinstance(c.get("country"), str):
            countries.append(c["country"])
    brand_hq = (brand.get("hq_country") or "").strip().upper()
    sells = brand.get("sells_in_countries")
    if brand_hq and brand_hq in {c.upper() for c in countries}:
        return True, {"country": brand_hq}
    # Global brands match any talent — return the talent's top market.
    if isinstance(sells, str) and sells.lower() == "global" and countries:
        return True, {"country": countries[0]}
    return False, {}


def _eval_past_brand_eligible_reengagement(
    *, talent: dict[str, Any], brand: dict[str, Any], **_: Any
) -> tuple[bool, dict[str, Any]]:
    brand_key = (brand.get("name") or "").strip().lower()
    if not brand_key:
        return False, {}
    if brand_key in _competitor_brands(talent):
        return True, {"brand_name": brand.get("name")}
    return False, {}


def _eval_always(*_: Any, **__: Any) -> tuple[bool, dict[str, Any]]:
    return True, {}


_EVALUATORS: dict[str, Any] = {
    "talent_worked_with_competitor": _eval_talent_worked_with_competitor,
    "talent_worked_in_same_industry": _eval_talent_worked_in_same_industry,
    "similar_talent_partnered_with_brand": _eval_similar_talent_partnered_with_brand,
    "multiple_similar_talents_with_brand": _eval_multiple_similar_talents_with_brand,
    "niche_primary_affinity": _eval_niche_primary_affinity,
    "iab_demographic_overlap": _eval_iab_demographic_overlap,
    "gender_skew_match": _eval_gender_skew_match,
    "geo_top_country_match": _eval_geo_top_country_match,
    "past_brand_eligible_reengagement": _eval_past_brand_eligible_reengagement,
    "always_for_buyer": _eval_always,
    "always_for_influencer": _eval_always,
    "always_for_gatekeeper": _eval_always,
    "always_for_champion": _eval_always,
}


def evaluate_trigger(
    trigger_type: str,
    *,
    talent: dict[str, Any],
    contact: dict[str, Any],
    brand: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    """Evaluate one trigger; return (fires, merge_fields).

    Unsupported triggers fail soft to (False, {}).
    """
    fn = _EVALUATORS.get(trigger_type)
    if fn is None:
        return False, {}
    return fn(talent=talent, contact=contact, brand=brand)


def filter_angles(
    *,
    angles: Sequence[PitchAngle],
    talent: dict[str, Any],
    contact: dict[str, Any],
    brand: dict[str, Any],
    step_number: int,
    decision_role: str,
    preferred_categories: list[str] | None = None,
    excluded_categories: list[str] | None = None,
    max_candidates: int = 10,
) -> list[dict[str, Any]]:
    """Return a ranked candidate list for one step.

    Each entry is ``{angle: PitchAngle, merge_fields: dict, score: float}``;
    sorted highest-strength first. Caller passes the top-K to the LLM.
    """
    excluded = {(c or "").strip().lower() for c in (excluded_categories or [])}
    preferred = {(c or "").strip().lower() for c in (preferred_categories or [])}
    role = (decision_role or "").strip().lower()

    candidates: list[dict[str, Any]] = []
    for angle in angles:
        data = dict(angle.data or {})
        # Step + role applicability.
        if step_number not in (data.get("applicable_to_steps") or []):
            continue
        applicable_roles = data.get("applicable_to_decision_roles") or []
        if role and role not in applicable_roles:
            continue
        category = (angle.category or "").strip().lower()
        if category in excluded:
            continue
        # Trigger evaluation.
        trigger = (data.get("trigger") or {}).get("type")
        if not isinstance(trigger, str):
            continue
        fires, merge_fields = evaluate_trigger(trigger, talent=talent, contact=contact, brand=brand)
        if not fires:
            continue
        # Required merge-field presence.
        required = data.get("merge_fields_required") or []
        if any(merge_fields.get(f) in (None, "") for f in required):
            continue
        # Boost score when category is preferred.
        base = float(angle.authored_strength_score or 0.0)
        boost = 0.15 if category in preferred else 0.0
        candidates.append(
            {
                "angle": angle,
                "merge_fields": merge_fields,
                "score": min(1.0, base + boost),
            }
        )

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:max_candidates]
