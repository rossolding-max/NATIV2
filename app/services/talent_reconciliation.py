"""Step 4 — reconciliation of media-pack extraction candidates.

The operator (or the CLI wizard) reviews each ``ExtractionCandidate``
produced by Step 3 and emits one ``ReconciliationDecision`` per
candidate:

- ``accept`` — apply the candidate's value as-is.
- ``edit``  — apply an operator-supplied value instead.
- ``reject`` — drop the candidate; no patch.

This service translates a batch of decisions into a single deep-merge
patch (compatible with ``TalentOnboardingService.apply_data_patch``)
and records provenance under ``data.extraction_provenance[field_path]``
so downstream callers can see which fields came from extraction vs the
questionnaire.

Per ``docs/onboarding_workflow.md`` § Step 4: only fields the operator
explicitly accepts (or edits) make it into ``talent.data``. Rejected
candidates are persisted under provenance with ``action: rejected``
so the audit trail is complete.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal


@dataclass(frozen=True)
class ReconciliationDecision:
    """One operator decision against a Step-3 candidate."""

    field_path: str
    action: Literal["accept", "edit", "reject"]
    edited_value: Any = None
    source_artefact_id: str | None = None


def _set_path(data: dict[str, Any], dotted_path: str, value: Any) -> None:
    """Set a value at a dotted path, creating intermediate dicts."""
    parts = dotted_path.split(".")
    current = data
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def build_reconciliation_patch(
    decisions: list[ReconciliationDecision],
    *,
    candidates_by_path: dict[str, Any],
) -> dict[str, Any]:
    """Produce the JSONB diff to merge into ``talent.data``.

    ``candidates_by_path`` maps ``field_path`` -> the original candidate
    value (so ``accept`` can recover what the LLM proposed without the
    caller having to repeat it in the request body).

    Provenance lands under ``extraction_provenance[<field_path>]`` with
    a small audit blob per decision — ``action``, the value applied (if
    any), the source artefact, and a timestamp. This lets later steps
    distinguish "user typed this" from "LLM proposed it, agent accepted".
    """
    patch: dict[str, Any] = {}
    provenance: dict[str, dict[str, Any]] = {}
    now_iso = datetime.now(UTC).isoformat()

    for decision in decisions:
        prov_entry: dict[str, Any] = {
            "action": decision.action,
            "decided_at": now_iso,
        }
        if decision.source_artefact_id:
            prov_entry["source_artefact_id"] = decision.source_artefact_id

        if decision.action == "accept":
            if decision.field_path not in candidates_by_path:
                # Caller asked to accept a field with no matching candidate —
                # nothing to do; record the orphan decision for audit.
                prov_entry["note"] = "accept-with-no-candidate"
                provenance[decision.field_path] = prov_entry
                continue
            value = candidates_by_path[decision.field_path]
            _set_path(patch, decision.field_path, value)
            prov_entry["value_applied"] = value
        elif decision.action == "edit":
            value = decision.edited_value
            _set_path(patch, decision.field_path, value)
            prov_entry["value_applied"] = value
            prov_entry["original_candidate"] = candidates_by_path.get(decision.field_path)
        else:  # reject
            prov_entry["original_candidate"] = candidates_by_path.get(decision.field_path)

        provenance[decision.field_path] = prov_entry

    if provenance:
        patch["extraction_provenance"] = provenance
    return patch
