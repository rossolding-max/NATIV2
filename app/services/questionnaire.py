"""Step 5 — talent-onboarding questionnaire.

v0.1 uses a deterministic rule table: given the current talent.data, the
service returns the next unanswered question. Question order is:

  identity (pronouns / bio / DOB)
    -> content profile (niches / languages)
    -> brand preferences (preferred / blocked industries + red lines)
    -> contact (email / phone)
    -> financial (target commission rate / rate card).

Agency-wide pieces — billing legal name, billing country, VAT/tax ID,
commission MODEL, default usage rights, contract template — are NOT
asked here. They live in agency onboarding (M4 + V2 follow-up).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Question:
    """One question for the UI/CLI to render."""

    field_path: str
    label: str
    kind: str
    required: bool
    choices_source: str | None = None


_QUESTIONNAIRE: list[Question] = [
    # ── A. Identity ──────────────────────────────────────────────────
    Question(
        field_path="pronouns",
        label="Pronouns",
        kind="enum_one",
        required=False,
        choices_source="pronouns",
    ),
    Question(
        field_path="legal_name",
        label="Legal name (if different from stage name)",
        kind="text",
        required=False,
    ),
    Question(
        field_path="gender_identity",
        label="Gender identity",
        kind="enum_one_or_text",
        required=False,
        choices_source="gender_identity",
    ),
    Question(
        field_path="bio",
        label="Bio (1-3 sentences)",
        kind="multiline",
        required=False,
    ),
    Question(
        field_path="date_of_birth",
        label="Date of birth (YYYY-MM-DD)",
        kind="date_iso",
        required=False,
    ),
    Question(
        field_path="career_start_year",
        label="Year started creating professionally (e.g. 2018)",
        kind="number_int",
        required=False,
    ),
    # ── B. Content profile ───────────────────────────────────────────
    Question(
        field_path="content_niches",
        label="Content niches",
        kind="enum_multi",
        required=False,
        choices_source="niches",
    ),
    Question(
        field_path="professional_roles",
        label="Other professional roles (besides content creator)",
        kind="enum_multi",
        required=False,
        choices_source="professional_roles",
    ),
    Question(
        field_path="content_pillars",
        label="Signature content pillars / formats (comma-separated, e.g. 'GRWM, morning routines, BTS')",
        kind="csv",
        required=False,
    ),
    Question(
        field_path="languages",
        label="Languages (BCP-47 codes, comma-separated, e.g. 'en, en-GB')",
        kind="csv",
        required=False,
    ),
    # ── C. Brand preferences ─────────────────────────────────────────
    Question(
        field_path="brand_preferences.preferred_industries",
        label="Preferred industries",
        kind="enum_multi",
        required=False,
        choices_source="industries",
    ),
    Question(
        field_path="brand_preferences.blocked_industries",
        label="Blocked industries",
        kind="enum_multi",
        required=False,
        choices_source="industries",
    ),
    Question(
        field_path="brand_preferences.values_red_lines",
        label="Values-based red lines (free-form, comma-separated)",
        kind="csv",
        required=False,
    ),
    # ── D. Contact ───────────────────────────────────────────────────
    Question(
        field_path="contact.email",
        label="Brand-reply email address",
        kind="email",
        required=True,
    ),
    Question(
        field_path="contact.phone",
        label="Phone (optional)",
        kind="phone",
        required=False,
    ),
    # ── E. Financial (LAST) ──────────────────────────────────────────
    Question(
        field_path="commission_override.rate",
        label="Target commission rate for this talent (decimal 0-1)",
        kind="number_decimal",
        required=False,
    ),
    Question(
        field_path="rate_card",
        label="Rate card (per-platform pricing per deliverable)",
        kind="rate_card",
        required=False,
    ),
]


# Static choice sets for picker-style prompts. ``pronouns`` is inline
# because there's no taxonomy file for it; ``niches`` / ``industries``
# load from ``data/`` via ``app.utils.taxonomies``.
_STATIC_CHOICES: dict[str, list[tuple[str, str]]] = {
    "pronouns": [
        ("she/her", "she/her"),
        ("he/him", "he/him"),
        ("they/them", "they/them"),
        ("she/they", "she/they"),
        ("he/they", "he/they"),
        ("prefer-not-to-say", "Prefer not to say"),
    ],
    "gender_identity": [
        ("female", "Female"),
        ("male", "Male"),
        ("non-binary", "Non-binary"),
        ("prefer-not-to-say", "Prefer not to say"),
    ],
    # Must match the enum in ``schemas/talent.schema.json`` -> properties.professional_roles.items.enum
    "professional_roles": [
        ("creator", "Content creator"),
        ("actor", "Actor"),
        ("comedian", "Comedian"),
        ("athlete", "Athlete"),
        ("musician", "Musician"),
        ("model", "Model"),
        ("writer", "Writer"),
        ("podcaster", "Podcaster"),
        ("speaker", "Public speaker"),
        ("founder", "Founder / entrepreneur"),
        ("executive", "Executive"),
        ("journalist", "Journalist"),
        ("chef", "Chef"),
        ("designer", "Designer"),
    ],
}


def static_choices(name: str) -> list[tuple[str, str]] | None:
    """Return a static (value, label) choice list, or None if not known."""
    return _STATIC_CHOICES.get(name)


def all_questions() -> list[Question]:
    """Expose the ordered question list (used by the CLI wizard)."""
    return list(_QUESTIONNAIRE)


def _get_path(data: dict[str, Any], dotted_path: str) -> Any:
    cur: Any = data
    for part in dotted_path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _set_path(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    cur = data
    for part in parts[:-1]:
        if part not in cur or not isinstance(cur[part], dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value


def _is_unanswered(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return bool(isinstance(value, list | dict) and not value)


def next_question(data: dict[str, Any]) -> Question | None:
    """Return the first unanswered question in the ordered rule table."""
    for q in _QUESTIONNAIRE:
        if _is_unanswered(_get_path(data, q.field_path)):
            return q
    return None


def build_patch_for_answer(field_path: str, value: Any) -> dict[str, Any]:
    """Translate a (field_path, value) answer into the JSONB diff shape."""
    patch: dict[str, Any] = {}
    _set_path(patch, field_path, value)
    return patch
