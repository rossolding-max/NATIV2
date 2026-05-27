"""Step 7.5 — contract template setup + GAP-08 version bump.

Mirrors M4's GAP-07 fix for the invoice template, but for talent
contracts. Server-side semver patch-bump on changes to MATERIAL fields:

- ``markdown_source``
- ``merge_field_definitions``
- ``clause_applicability_rules``
- ``narrative_placeholders``
- ``default_governing_law``
- ``default_jurisdiction``

Cosmetic-only fields (e.g. ``legal_reviewer_id``,
``based_on_starter_template_id``) do NOT bump the version.

Starter templates live under ``data/contract_template_starters/{slug}.md``
and are loaded on demand. v0.1 ships three starters:
``management``, ``talent-agency``, ``brand-paid-promotion``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.errors import ValidationError

_MATERIAL_FIELDS: frozenset[str] = frozenset(
    {
        "markdown_source",
        "merge_field_definitions",
        "clause_applicability_rules",
        "narrative_placeholders",
        "default_governing_law",
        "default_jurisdiction",
    }
)

# Inline starter templates as a fallback when the data dir is empty in
# dev / CI. M5 ships these minimally; M6+ may extend.
_INLINE_STARTERS: dict[str, str] = {
    "management": """\
# Talent Management Agreement

**Talent:** {{talent_name}}
**Agency:** {{agency_name}}
**Effective date:** {{effective_date}}

## Scope

{{scope_description}}

## Commission

The Agency receives {{commission_rate}}% of all gross revenues per the
default model {{commission_model}}.

{{#if termination_clause}}
## Termination

{{termination_terms}}
{{/if}}

Signed: {{talent_signature}} / {{agency_signature}}
""",
    "talent-agency": """\
# Talent-Agency Representation Agreement

This agreement is between {{talent_name}} ("Talent") and {{agency_name}}
("Agency"), effective {{effective_date}}.

## Representation scope

{{representation_scope}}

## Term

{{term_length}}, auto-renewing per {{renewal_terms}}.

Signed: {{talent_signature}} / {{agency_signature}}
""",
    "brand-paid-promotion": """\
# Brand Paid-Promotion Master Agreement

Master terms governing brand deals brokered by {{agency_name}} on behalf
of {{talent_name}}.

## Deliverable terms

{{deliverable_defaults}}

## Usage rights

{{usage_rights_default}}

{{#if exclusivity}}
## Exclusivity

{{exclusivity_terms}}
{{/if}}

Signed: {{talent_signature}} / {{agency_signature}}
""",
}


@lru_cache(maxsize=8)
def _starter_template(slug: str) -> str | None:
    """Load a starter template by slug. Falls back to the inline dict."""
    repo = Path(__file__).resolve().parents[2]
    path = repo / "data" / "contract_template_starters" / f"{slug}.md"
    if path.exists():
        return path.read_text()
    return _INLINE_STARTERS.get(slug)


def reset_starter_cache_for_tests() -> None:
    _starter_template.cache_clear()


def available_starters() -> list[str]:
    """Slugs the agency can adopt."""
    return sorted(_INLINE_STARTERS.keys())


def _bump_patch(version: str) -> str:
    """Increment the patch component of a semver string. Default base 0.0.0."""
    parts = version.split(".") if version else []
    while len(parts) < 3:
        parts.append("0")
    try:
        major, minor, patch = (int(p) for p in parts[:3])
    except ValueError as exc:
        raise ValidationError(
            f"invalid contract template_version {version!r}",
            field="template_version",
        ) from exc
    return f"{major}.{minor}.{patch + 1}"


def materialise_contract_template_patch(
    *, current: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    """Compute the persisted shape of a contract-template patch.

    Strips client-supplied ``template_version`` + ``template_updated_at``
    (both server-authoritative). Patch-bumps version on any change to
    material fields; pure cosmetic changes preserve the existing version.
    """
    sanitised = {
        k: v for k, v in incoming.items() if k not in {"template_version", "template_updated_at"}
    }

    material_changed = any(
        field in sanitised and sanitised[field] != current.get(field) for field in _MATERIAL_FIELDS
    )

    merged: dict[str, Any] = dict(current)
    merged.update(sanitised)

    if material_changed or "template_version" not in current:
        merged["template_version"] = _bump_patch(current.get("template_version", "0.0.0"))
        merged["template_updated_at"] = datetime.now(UTC).isoformat()
    else:
        merged.setdefault("template_version", current.get("template_version", "1.0.0"))
        merged.setdefault("template_updated_at", current.get("template_updated_at"))

    return merged


def adopt_starter_template(starter_slug: str) -> dict[str, Any]:
    """Build the initial contract_template dict from a starter slug."""
    markdown = _starter_template(starter_slug)
    if markdown is None:
        raise ValidationError(
            f"unknown starter template slug {starter_slug!r}",
            field="based_on_starter_template_id",
            detail={"allowed": available_starters()},
        )
    now = datetime.now(UTC).isoformat()
    # Omit string fields when their value is unset — talent.schema.json
    # requires string types for default_governing_law / default_jurisdiction
    # / legal_reviewer_id when the key is present, so we leave them absent
    # until the user fills them in via PATCH.
    return {
        "based_on_starter_template_id": starter_slug,
        "markdown_source": markdown,
        "merge_field_definitions": [],
        "clause_applicability_rules": [],
        "narrative_placeholders": [],
        "template_version": "0.1.0",
        "template_updated_at": now,
    }


def validate_template_completeness(template: dict[str, Any]) -> list[str]:
    """Check every merge field + conditional clause is declared.

    Returns a list of human-readable error strings (empty on success).
    Scans ``markdown_source`` for ``{{merge_field}}`` and
    ``{{#if clause}}`` patterns and confirms each appears in the
    corresponding definitions array.
    """
    errors: list[str] = []
    markdown = template.get("markdown_source") or ""
    declared_fields = {
        d.get("name") for d in template.get("merge_field_definitions") or [] if isinstance(d, dict)
    }
    declared_clauses = {
        r.get("clause_id")
        for r in template.get("clause_applicability_rules") or []
        if isinstance(r, dict)
    }
    declared_narratives = {
        n.get("name") for n in template.get("narrative_placeholders") or [] if isinstance(n, dict)
    }

    import re

    for match in re.finditer(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", markdown):
        name = match.group(1)
        if name not in declared_fields and name not in declared_narratives:
            errors.append(f"merge field {{{{{name}}}}} is not declared")

    for match in re.finditer(r"\{\{\s*#if\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", markdown):
        clause_id = match.group(1)
        if clause_id not in declared_clauses:
            errors.append(f"conditional clause {{{{#if {clause_id}}}}} is not declared")

    return errors
