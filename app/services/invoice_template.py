"""Invoice template service — starter content + version bump + sequence.

Implements GAP-07 from ``docs/spec_methodology.md``: server-side
``template_version`` auto-bump on changes to material fields.

Material fields (any change → semver patch bump + ``template_updated_at`` refresh):
- ``markdown_source``
- ``tax_handling``
- ``invoice_footer``
- ``payment_instructions_markdown``
- ``default_payment_terms_days``

Cosmetic-only fields (e.g. ``invoice_number_prefix``, ``invoice_number_format``,
``tax_label``) do NOT trigger a bump.

The ``next_invoice_number`` helper is consumed by M14 (invoice pack
generation); M4 ships it so the contract is locked at the same time as the
counter is initialised in the agency_profile.data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import BusinessRuleError, ValidationError
from app.models.sqla.agency_profile import AgencyProfile

_MATERIAL_FIELDS: frozenset[str] = frozenset(
    {
        "markdown_source",
        "tax_handling",
        "invoice_footer",
        "payment_instructions_markdown",
        "default_payment_terms_days",
    }
)

STARTER_TEMPLATE_MARKDOWN = """\
# Invoice {invoice_number}

**From:** {agency_name}
{agency_address}

**To:** {brand_name}
{brand_billing_address}

**Issue date:** {issue_date}
**Due date:** {due_date}

---

## Services

| Description | Amount |
| --- | --- |
{line_items}

---

**Subtotal:** {subtotal}
{tax_line}
**Total due:** {total}

## Payment instructions

{payment_instructions}

---

{invoice_footer}
"""


def _bump_patch(version: str) -> str:
    """Increment the patch component of a semver string. Default base = 1.0.0."""
    parts = version.split(".") if version else []
    while len(parts) < 3:
        parts.append("0")
    try:
        major, minor, patch = (int(p) for p in parts[:3])
    except ValueError as exc:
        raise ValidationError(
            f"invalid invoice template_version {version!r}",
            field="template_version",
        ) from exc
    return f"{major}.{minor}.{patch + 1}"


def materialise_invoice_template_patch(
    *, current: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    """Compute the persisted shape of an invoice_template diff.

    Returns the dict the caller will pass to ``patch_data`` as
    ``{"invoice_template": <merged>}``. Strips client-supplied
    ``template_version`` and ``template_updated_at`` — both are
    authoritative on the server.

    If any material field differs from ``current``, ``template_version`` is
    bumped (patch) and ``template_updated_at`` is set to ``now()``.
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


async def next_invoice_number(session: AsyncSession, *, agency_id: UUID) -> str:
    """Atomically increment ``invoice_number_sequence`` + format per the template.

    Locks the agency_profile row with ``SELECT ... FOR UPDATE`` so concurrent
    invoice generation jobs don't collide. Caller commits the surrounding
    transaction; this function leaves the lock + UPDATE pending.
    """
    stmt = select(AgencyProfile).where(AgencyProfile.agency_id == agency_id).with_for_update()
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise BusinessRuleError("agency_profile not found", detail={"agency_id": str(agency_id)})

    data = dict(row.data or {})
    tpl = dict(data.get("invoice_template") or {})
    seq = int(tpl.get("invoice_number_sequence") or 1)
    fmt = tpl.get("invoice_number_format") or "INV-{YYYY}-{seq:04d}"

    formatted = fmt.format(
        YYYY=datetime.now(UTC).strftime("%Y"),
        seq=seq,
    )

    # Persist the bumped counter back.
    tpl["invoice_number_sequence"] = seq + 1
    data["invoice_template"] = tpl
    row.data = data
    await session.flush()
    return formatted
