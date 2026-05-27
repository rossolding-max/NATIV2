"""Phase 1 talent-onboarding state machine + JSON-Schema gate.

Mirrors the M4 ``AgencySetupService`` pattern: incremental patches DO NOT
validate the full schema (Phase 1 builds the talent step by step; early
patches will fail the schema until later steps fill in the required
arrays). Full validation runs at activate-time via
``check_ready_for_activation`` + ``validate_data_against_schema``.

Status transitions (column default is ``onboarding`` per the M1 SQLA model;
the workflow doc's term "draft" maps onto this):

  onboarding ────► active ────► archived
       ▲                 │
       └───── re-open ───┘
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from app.errors import BusinessRuleError, ValidationError
from app.repositories.talent import TalentRepository

_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    "onboarding": frozenset({"active"}),
    "active": frozenset({"archived", "onboarding"}),
    "archived": frozenset({"active"}),
}

_VALID_STATUSES: frozenset[str] = frozenset(_STATUS_TRANSITIONS.keys())


@lru_cache(maxsize=1)
def _load_schema() -> dict[str, Any]:
    """Load + cache the talent JSON Schema."""
    repo = Path(__file__).resolve().parents[2]
    schema_path = repo / "schemas" / "talent.schema.json"
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
            f"talent data invalid: {exc.message}",
            field=".".join(str(p) for p in exc.absolute_path) or None,
            detail={"path": list(exc.absolute_path), "validator": exc.validator},
        ) from exc


def check_ready_for_activation(data: dict[str, Any]) -> None:
    """Cross-field invariants on top of the JSON Schema.

    Per the M5 plan + onboarding workflow:
    - At least one platform with ``api_credentials.scope_validated_at``.
    - Every ``previous_brands[]`` entry has ``industry_id``.
    - ``billing_entity.legal_name`` present (required for invoicing).
    """
    platforms = data.get("platforms") or []
    if not platforms:
        raise BusinessRuleError(
            "cannot activate: no platforms connected",
            detail={"field": "platforms"},
        )
    if not any((p.get("api_credentials") or {}).get("scope_validated_at") for p in platforms):
        raise BusinessRuleError(
            "cannot activate: no platform has scope_validated_at — re-run OAuth",
            detail={"field": "platforms[].api_credentials.scope_validated_at"},
        )

    previous_brands = data.get("previous_brands") or []
    missing_industry = [idx for idx, b in enumerate(previous_brands) if not b.get("industry_id")]
    if missing_industry:
        raise BusinessRuleError(
            "cannot activate: some previous_brands[] entries are missing industry_id",
            detail={
                "field": "previous_brands[].industry_id",
                "missing_indices": missing_industry,
            },
        )

    billing = data.get("billing_entity") or {}
    if not billing.get("legal_name"):
        raise BusinessRuleError(
            "cannot activate: billing_entity.legal_name is required",
            detail={"field": "billing_entity.legal_name"},
        )


class TalentOnboardingService:
    """Orchestrates the 10-step Phase 1 flow against ``TalentRepository``.

    Per-step methods are intentionally thin so the REST router and the CLI
    wizard (Commit 3) drive the same code path.
    """

    def __init__(self, repo: TalentRepository) -> None:
        self._repo = repo

    async def apply_data_patch(
        self,
        talent_id: str,
        diff: dict[str, Any],
        *,
        validate_full: bool = False,
    ) -> dict[str, Any]:
        """Apply a JSONB diff to a talent. Schema-validate only when asked.

        Phase 1 builds the profile incrementally — early patches leave the
        document in a state that fails the full talent schema (no
        platforms, no billing entity, etc). The activate endpoint runs the
        full validator + cross-field guards instead.
        """
        instance = await self._repo.patch_data(talent_id, diff)
        if validate_full:
            validate_data_against_schema(dict(instance.data))
        return dict(instance.data)

    async def transition_status(self, talent_id: str, *, current: str, target: str) -> str:
        """Validate + apply a status transition."""
        validate_status_transition(current, target)
        updated = await self._repo.set_status(talent_id, target)
        return updated.status

    async def activate(self, talent_id: str) -> str:
        """Run final validation and flip ``status`` to ``active``."""
        row = await self._repo.get_by_talent_id(talent_id)
        if row is None:
            raise BusinessRuleError(
                "cannot activate: talent not found",
                detail={"talent_id": talent_id},
            )
        validate_data_against_schema(dict(row.data))
        check_ready_for_activation(dict(row.data))
        validate_status_transition(row.status, "active")
        updated = await self._repo.set_status(talent_id, "active")
        return updated.status
