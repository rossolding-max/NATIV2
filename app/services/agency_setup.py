"""Phase 0 agency-setup state machine + step orchestration.

Wraps ``AgencyProfileRepository`` calls with the transitions defined in
``docs/agency_setup_workflow.md``:

  setup_in_progress
       │
       │  (branding / agent / signature / invoice_template /
       │   commission_defaults / DNS records refreshed)
       ▼
  awaiting_dns
       │
       │  (DNS verified + mailbox provisioned)
       ▼
  warming_up
       │
       │  (Smartlead warmup_status = "complete")
       ▼
  active

Activate-time validation runs the full ``schemas/agency_profile.schema.json``
validator against ``data`` and confirms the cross-field requirements
(``sending_mailboxes[0].dns_records_verified == True`` AND
``sending_mailboxes[0].warmup_status == "complete"``).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

import jsonschema

from app.errors import BusinessRuleError, ValidationError
from app.repositories.agency_profile import AgencyProfileRepository

_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "setup_in_progress": frozenset({"awaiting_dns"}),
    "awaiting_dns": frozenset({"warming_up", "setup_in_progress"}),
    "warming_up": frozenset({"active", "awaiting_dns"}),
    "active": frozenset({"warming_up"}),  # demote on warmup regression
}

_VALID_STATUSES: frozenset[str] = frozenset(_STATUS_TRANSITIONS.keys())


@lru_cache(maxsize=1)
def _load_schema() -> dict[str, Any]:
    """Load + cache the agency_profile JSON Schema."""
    repo = Path(__file__).resolve().parents[2]
    schema_path = repo / "schemas" / "agency_profile.schema.json"
    return json.loads(schema_path.read_text())


def reset_schema_cache_for_tests() -> None:
    _load_schema.cache_clear()


def validate_status_transition(current: str, target: str) -> None:
    """Raise ``BusinessRuleError`` if the transition is not allowed."""
    if current == target:
        return
    if current not in _VALID_STATUSES:
        raise BusinessRuleError(
            f"unknown current status {current!r}",
            detail={"current": current, "target": target},
        )
    if target not in _VALID_STATUSES:
        raise BusinessRuleError(
            f"unknown target status {target!r}",
            detail={"current": current, "target": target},
        )
    if target not in _STATUS_TRANSITIONS[current]:
        raise BusinessRuleError(
            f"illegal status transition: {current} → {target}",
            detail={
                "current": current,
                "target": target,
                "allowed": sorted(_STATUS_TRANSITIONS[current]),
            },
        )


def validate_data_against_schema(data: dict[str, Any]) -> None:
    """Raise ``ValidationError`` if ``data`` doesn't satisfy the JSON Schema."""
    schema = _load_schema()
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise ValidationError(
            f"agency_profile data invalid: {exc.message}",
            field=".".join(str(p) for p in exc.absolute_path) or None,
            detail={"path": list(exc.absolute_path), "validator": exc.validator},
        ) from exc


def check_ready_for_activation(data: dict[str, Any]) -> None:
    """Beyond schema validation, confirm DNS + warmup cross-field invariants."""
    mailboxes = data.get("sending_mailboxes") or []
    if not mailboxes:
        raise BusinessRuleError(
            "cannot activate: no sending_mailbox configured",
            detail={"field": "sending_mailboxes"},
        )
    mbox = mailboxes[0]
    if not mbox.get("dns_records_verified"):
        raise BusinessRuleError(
            "cannot activate: DNS records not verified",
            detail={"field": "sending_mailboxes[0].dns_records_verified"},
        )
    if mbox.get("warmup_status") != "complete":
        raise BusinessRuleError(
            "cannot activate: mailbox warmup not complete",
            detail={
                "field": "sending_mailboxes[0].warmup_status",
                "current": mbox.get("warmup_status"),
            },
        )


class AgencySetupService:
    """Orchestrates the 9-step Phase 0 setup against the repository.

    Stateless except for the bound repository. Service-layer methods are
    intentionally thin so the same logic is exercised by both the REST
    endpoints and the CLI wizard (PR 3).
    """

    def __init__(self, repo: AgencyProfileRepository) -> None:
        self._repo = repo

    async def apply_data_patch(
        self, agency_id: UUID, diff: dict[str, Any], *, validate_full: bool = False
    ) -> dict[str, Any]:
        """Apply a diff to ``data`` and (optionally) validate the result.

        v0.1 always validates the merged ``data`` against the JSON schema —
        any patch leaving the row in an invalid state is rejected. The
        ``validate_full`` flag is kept for future relaxation (currently a
        no-op since every write validates).
        """
        _ = validate_full
        instance = await self._repo.patch_data(agency_id, diff)
        validate_data_against_schema(instance.data)
        return dict(instance.data)

    async def transition_status(self, agency_id: UUID, *, current: str, target: str) -> str:
        """Validate + apply a status transition. Returns the new status."""
        validate_status_transition(current, target)
        updated = await self._repo.set_status(agency_id, target)
        return updated.status

    async def activate(self, agency_id: UUID) -> str:
        """Run final validation and flip ``status`` to ``active``."""
        row = await self._repo.get_singleton()
        if row is None or row.agency_id != agency_id:
            raise BusinessRuleError(
                "cannot activate: agency_profile singleton not found",
                detail={"agency_id": str(agency_id)},
            )
        validate_data_against_schema(dict(row.data))
        check_ready_for_activation(dict(row.data))
        validate_status_transition(row.status, "active")
        updated = await self._repo.set_status(agency_id, "active")
        return updated.status
