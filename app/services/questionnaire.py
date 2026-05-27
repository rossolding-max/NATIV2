"""Step 5 — adaptive questionnaire.

v0.1 uses a deterministic rule table: given the current talent.data, the
service returns the next unanswered required-field question. The full
LLM-driven branching (workflow doc § Step 5) lands when M11+ artefact
generation reveals which fields most commonly need follow-up.

Field-path notation matches JSON Schema (``billing_entity.legal_name`` etc.).
Caller patches the response into the talent via ``apply_data_patch``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Ordered list of (field_path, prompt, kind, required) tuples. Order is
# the question order — first missing one is returned.
_QUESTIONNAIRE: list[tuple[str, str, str, bool]] = [
    ("pronouns", "What pronouns should we use in outreach?", "text", False),
    ("languages", "Which languages do you create content in?", "list", False),
    (
        "contact.email",
        "What's the best email address for brand reply traffic?",
        "email",
        True,
    ),
    ("contact.phone", "Optional phone number for urgent brand requests?", "text", False),
    (
        "billing_entity.legal_name",
        "Legal entity name to appear on invoices (the company or sole-trader name).",
        "text",
        True,
    ),
    (
        "billing_entity.country",
        "Two-letter country code of your billing entity (e.g. US, GB).",
        "text",
        True,
    ),
    (
        "billing_entity.tax_id",
        "Tax / VAT identifier (optional but recommended for cross-border invoicing).",
        "text",
        False,
    ),
    (
        "working_terms.default_usage_rights",
        "Default usage rights term (e.g. '6 months organic, 3 months paid').",
        "text",
        False,
    ),
    (
        "brand_preferences.preferred_industries",
        "Industries you actively want to work with (free-text or industry slugs).",
        "list",
        False,
    ),
    (
        "brand_preferences.never_work_with",
        "Industries / brands you refuse to work with.",
        "list",
        False,
    ),
    (
        "commission_override.rate",
        (
            "Override the agency's default commission rate for THIS talent? "
            "(decimal 0-1; blank to inherit)"
        ),
        "number",
        False,
    ),
    (
        "commission_override.model",
        "Override commission model? (agency_invoices_brand_pays_talent_net | "
        "talent_invoices_brand_agency_invoices_talent | "
        "talent_invoices_brand_talent_pays_agency; blank to inherit)",
        "text",
        False,
    ),
]


@dataclass(frozen=True)
class Question:
    """One question for the UI/CLI to render."""

    field_path: str
    prompt: str
    kind: str
    required: bool


def _get_path(data: dict[str, Any], dotted_path: str) -> Any:
    """Walk a dotted path through nested dicts; return ``None`` if missing."""
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        if part not in current:
            return None
        current = current[part]
    return current


def _set_path(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Set a value at a dotted path, creating intermediate dicts."""
    parts = dotted_path.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def next_question(data: dict[str, Any]) -> Question | None:
    """Return the first unanswered required-or-recommended question."""
    for field_path, prompt, kind, required in _QUESTIONNAIRE:
        if _get_path(data, field_path) is None:
            return Question(
                field_path=field_path,
                prompt=prompt,
                kind=kind,
                required=required,
            )
    return None


def build_patch_for_answer(field_path: str, value: Any) -> dict[str, Any]:
    """Translate a (field_path, value) answer into the JSONB diff shape."""
    patch: dict[str, Any] = {}
    _set_path(patch, field_path, value)
    return patch
