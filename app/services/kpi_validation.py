"""KPI honesty-floor enforcement for ``brand_deal`` writes.

Per ``docs/brand_deals_workflow.md``:

  Every populated KPI value MUST carry ``source`` + ``as_of``. Missing
  metrics are omitted; never null, never zero, never guessed.

The shared ``kpiMetric`` schema (``schemas/_shared/kpi_metric.schema.json``)
requires ``value`` + ``source``. M6 adds the ``as_of`` requirement at
write time because the entire premise of the deal layer is verifiable
citation material — a value without a date is not citable.

The service raises ``ValidationError`` with a structured field path so
the REST layer surfaces inline error messages per the M5 pattern.

Also surfaces "suspicious value" flags (engagement_rate_pct > 100, etc.).
These do NOT block the write — they're logged for the agent to review.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.errors import ValidationError

# Valid ``source`` enum from ``kpi_metric.schema.json``.
_VALID_SOURCES: frozenset[str] = frozenset(
    {
        "platform_verified",
        "brand_reported",
        "third_party",
        "calculated",
        "self_reported",
        "estimated",
    }
)

# KPIs where value is a percentage 0-100. Anything > 100 is suspicious.
_PCT_METRICS: frozenset[str] = frozenset(
    {
        "engagement_rate_pct",
        "video_completion_rate_pct",
        "ctr_pct",
        "completion_rate_pct",
    }
)


def validate_kpi_metric(metric_name: str, metric: Any) -> list[str]:
    """Validate one populated KPI metric. Returns a list of error strings.

    Empty list means the metric is well-formed. Caller treats any
    non-empty list as a ``ValidationError`` payload.
    """
    errors: list[str] = []
    if not isinstance(metric, dict):
        return [f"{metric_name}: must be an object with value + source + as_of"]
    if "value" not in metric:
        errors.append(f"{metric_name}: missing required 'value'")
    elif not isinstance(metric["value"], int | float):
        errors.append(f"{metric_name}: 'value' must be a number")
    elif metric["value"] < 0:
        errors.append(f"{metric_name}: 'value' must be >= 0")

    source = metric.get("source")
    if not source:
        errors.append(f"{metric_name}: missing required 'source' enum")
    elif source not in _VALID_SOURCES:
        errors.append(
            f"{metric_name}: 'source' must be one of {sorted(_VALID_SOURCES)} (got {source!r})"
        )

    as_of = metric.get("as_of")
    if not as_of:
        # M6 honesty-floor extension over the shared schema: as_of is REQUIRED.
        errors.append(f"{metric_name}: missing required 'as_of' (ISO 8601 date)")
    elif isinstance(as_of, str):
        try:
            parsed = date.fromisoformat(as_of)
        except ValueError:
            errors.append(f"{metric_name}: 'as_of' must be ISO 8601 (YYYY-MM-DD)")
        else:
            if parsed > datetime.now(UTC).date():
                errors.append(f"{metric_name}: 'as_of' is in the future ({as_of})")
    return errors


def flag_suspicious_values(metric_name: str, metric: Any) -> list[str]:
    """Non-blocking suspicion flags — agent reviews but the write proceeds."""
    flags: list[str] = []
    value = metric.get("value") if isinstance(metric, dict) else None
    if not isinstance(value, int | float):
        return flags
    if metric_name in _PCT_METRICS and value > 100:
        flags.append(f"{metric_name}: percentage value {value} exceeds 100")
    if metric_name == "engagement_rate_pct" and value > 30:
        flags.append(
            f"{metric_name}: engagement rate {value}% is unusually high; "
            "please double-check the source figure"
        )
    return flags


def validate_deal_kpis(kpis: dict[str, Any]) -> list[str]:
    """Validate every populated metric inside the Kpis container.

    Returns aggregated error strings across all metrics. Missing metrics
    (where the whole key is absent) are LEGAL; they just don't get
    rendered downstream.
    """
    errors: list[str] = []
    for metric_name, metric in kpis.items():
        if metric is None:
            continue  # omitted metric — legal absence
        errors.extend(validate_kpi_metric(metric_name, metric))
    return errors


# ── JSON-schema validation against the deal-level subschema ───────────


_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "brand_deal.schema.json"
_deal_validator: Any = None


def _get_deal_validator() -> Any:
    """Lazy-load + cache the deal-level subschema validator.

    The repo's ``brand_deal.schema.json`` is a per-talent file shape; the
    deal-level subschema lives under ``$defs/deal``. We validate single
    deal payloads against that subschema, with the shared ``kpiMetric``
    schema pre-registered so its ``$ref`` resolves offline.
    """
    global _deal_validator
    if _deal_validator is not None:
        return _deal_validator
    import json

    import jsonschema  # type: ignore[import-untyped]

    full = json.loads(_SCHEMA_PATH.read_text())
    deal_schema = full.get("$defs", {}).get("deal")
    if deal_schema is None:
        raise RuntimeError("brand_deal.schema.json missing $defs.deal")

    # Pre-register the shared kpiMetric schema so cross-file $refs resolve
    # without hitting the network.
    shared_dir = _SCHEMA_PATH.parent / "_shared"
    store: dict[str, Any] = {full.get("$id", ""): full}
    if shared_dir.exists():
        for shared_path in shared_dir.glob("*.schema.json"):
            shared_doc = json.loads(shared_path.read_text())
            schema_id = shared_doc.get("$id")
            if schema_id:
                store[schema_id] = shared_doc

    # ``jsonschema.RefResolver`` is deprecated in favour of ``referencing.Registry``,
    # but the M5 talent validator uses the simpler top-level ``jsonschema.validate``
    # which doesn't need a registry. M6 needs cross-file ``$ref`` resolution
    # against the local ``_shared`` directory; the RefResolver+store form is the
    # shortest path. Migration to ``referencing`` tracked as a future polish item.
    resolver = jsonschema.RefResolver.from_schema(  # pyright: ignore[reportDeprecated]
        full, store=store
    )
    _deal_validator = jsonschema.Draft202012Validator(deal_schema, resolver=resolver)
    return _deal_validator


def validate_deal_against_schema(deal: dict[str, Any]) -> None:
    """Raise ``ValidationError`` if the deal payload violates the deal subschema.

    Errors carry the field path for surfacing in the REST envelope.
    """
    validator = _get_deal_validator()
    errors = sorted(validator.iter_errors(deal), key=lambda e: e.path)
    if not errors:
        return
    first = errors[0]
    path_parts = [str(p) for p in first.absolute_path]
    field = ".".join(path_parts) if path_parts else None
    raise ValidationError(
        f"deal invalid: {first.message}",
        field=field,
        detail={
            "path": list(first.absolute_path),
            "validator": first.validator,
            "all_errors": [
                {
                    "path": list(e.absolute_path),
                    "message": e.message,
                    "validator": e.validator,
                }
                for e in errors
            ],
        },
    )


def validate_deal_payload(deal: dict[str, Any]) -> list[str]:
    """Run full validation: schema + honesty-floor + return suspicion flags.

    Raises ``ValidationError`` on schema or honesty-floor failures.
    Returns the list of non-blocking suspicion flags for the caller to
    log / surface as a warning.
    """
    validate_deal_against_schema(deal)

    kpis = deal.get("kpis") or {}
    honesty_errors = validate_deal_kpis(kpis)
    if honesty_errors:
        raise ValidationError(
            f"deal kpis violate honesty floor: {honesty_errors[0]}",
            field="kpis",
            detail={"errors": honesty_errors},
        )

    flags: list[str] = []
    for metric_name, metric in kpis.items():
        if isinstance(metric, dict):
            flags.extend(flag_suspicious_values(metric_name, metric))
    return flags
