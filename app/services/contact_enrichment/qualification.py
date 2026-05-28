"""Per-contact qualification scoring — mirrors ``discovery/qualification.py``.

Computes a 0-1 score per ``EnrichedContact`` from positive + negative
signals about how good a pitch target they are.

Tiers:
- ``qualified`` >= 0.60 — default include in primary outreach
- ``speculative`` 0.30-0.60 — include but surface for agent review
- ``unqualified`` < 0.30 — drop unless explicitly opted-in
"""

from __future__ import annotations

from typing import Any, Literal

from app.services.contact_enrichment._models import EnrichedContact, QualifiedContact

DEFAULT_QUALIFICATION_THRESHOLD: float = 0.30

_SIGNAL_WEIGHTS: dict[str, float] = {
    "buyer_decision_role": 0.30,
    "senior_seniority": 0.20,
    "marketing_function": 0.20,
    "verified_email": 0.10,
    "champion_decision_role": 0.20,
    # Negative signals
    "micro_brand_at_assistant_level": -0.20,
    "gatekeeper_only": -0.10,
    "unverified_email_for_high_seniority": 0.0,  # reserved
}

_SENIOR_TIERS: frozenset[str] = frozenset({"founder", "c_suite", "svp", "vp"})
_MARKETING_FUNCTION_KEYWORDS: tuple[str, ...] = (
    "marketing",
    "influencer",
    "partnerships",
    "brand",
    "growth",
    "community",
    "social",
)

QualificationTier = Literal["qualified", "speculative", "unqualified"]


def _classify_tier(score: float) -> QualificationTier:
    if score >= 0.60:
        return "qualified"
    if score >= 0.30:
        return "speculative"
    return "unqualified"


def _signal(*, name: str, value: float, detail: str) -> dict[str, Any]:
    return {"signal": name, "weight": value, "details": detail}


def _is_marketing_function(title: str | None) -> bool:
    if not title:
        return False
    lower = title.lower()
    return any(k in lower for k in _MARKETING_FUNCTION_KEYWORDS)


def qualify_contact(contact: EnrichedContact) -> QualifiedContact:
    """Compute the qualification for one contact."""
    signals: list[dict[str, Any]] = []
    score = 0.0

    if contact.decision_role == "buyer":
        signals.append(
            _signal(
                name="buyer_decision_role",
                value=_SIGNAL_WEIGHTS["buyer_decision_role"],
                detail="LLM classified as buyer.",
            )
        )
        score += _SIGNAL_WEIGHTS["buyer_decision_role"]
    elif contact.decision_role == "champion":
        signals.append(
            _signal(
                name="champion_decision_role",
                value=_SIGNAL_WEIGHTS["champion_decision_role"],
                detail="LLM classified as champion / advocate.",
            )
        )
        score += _SIGNAL_WEIGHTS["champion_decision_role"]
    elif contact.decision_role == "gatekeeper":
        signals.append(
            _signal(
                name="gatekeeper_only",
                value=_SIGNAL_WEIGHTS["gatekeeper_only"],
                detail="Gatekeeper — access only, not decision.",
            )
        )
        score += _SIGNAL_WEIGHTS["gatekeeper_only"]

    seniority = (contact.seniority or "").strip().lower()
    if seniority in _SENIOR_TIERS:
        signals.append(
            _signal(
                name="senior_seniority",
                value=_SIGNAL_WEIGHTS["senior_seniority"],
                detail=f"seniority={seniority}.",
            )
        )
        score += _SIGNAL_WEIGHTS["senior_seniority"]

    if _is_marketing_function(contact.title):
        signals.append(
            _signal(
                name="marketing_function",
                value=_SIGNAL_WEIGHTS["marketing_function"],
                detail=f"title='{contact.title}' contains marketing keyword.",
            )
        )
        score += _SIGNAL_WEIGHTS["marketing_function"]

    status = (contact.email_verification_status or "").strip().lower()
    if status == "verified":
        signals.append(
            _signal(
                name="verified_email",
                value=_SIGNAL_WEIGHTS["verified_email"],
                detail="Apollo-verified email.",
            )
        )
        score += _SIGNAL_WEIGHTS["verified_email"]

    final = max(0.0, min(1.0, score))
    return QualifiedContact(
        contact=contact,
        qualification_score=final,
        qualification_tier=_classify_tier(final),
        qualification_signals=signals,
    )
