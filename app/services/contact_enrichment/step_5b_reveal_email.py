"""Step 5b — operator-triggered email reveal (M8.1 Phase C).

Phase A surfaces 30-80 contacts per brand WITHOUT calling Apollo
``/people/match`` for emails. Phase B classifies each with
``decision_role`` + ``outreach_recommendation`` flags. The operator
reviews the badged list in the UI and selects which contacts they
actually want to outreach.

THIS module runs when the operator hits the bulk-reveal endpoint
(``POST /api/v1/brands/{brand_id}/contact-emails/reveal``). For each
selected ``contact_id``:

  1. Look up the row + its LinkedIn URL + the brand's domain.
  2. Fire ``ApolloClient.match_person()`` (one HTTP call per contact;
     Apollo has no bulk endpoint; the global 60/min rate-limit applies
     so a bulk of 10 contacts takes ~10 seconds).
  3. Apply the M8 strict honesty floor: keep the returned email only if
     Apollo flagged it ``verified`` or ``catchall``. Anything else (or
     no email returned) → email stays NULL on the row, but
     ``verification_status`` records why ("unverified", "bounced",
     "not_found").
  4. Always set ``revealed_at = now()`` so the UI shows "we tried"
     even when the reveal returned no usable email.

The strict honesty floor moved verbatim from the original
``step_5_email_verify`` — no pattern-guessing, no third-party
verifiers. v0.2 may add Hunter / NeverBounce as fallback verifiers
(see ``docs/v2_deferred_requirements.md``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.repositories.brand_contact import BrandContactRepository
from app.utils.logging import get_logger
from app.vendors.apollo import ApolloClient

log = get_logger(__name__)


ALLOWED_STATUSES: frozenset[str] = frozenset({"verified", "catchall"})


def _apply_honesty_floor(
    email_address: str | None, raw_status: str | None
) -> tuple[str | None, str]:
    """Return (email_to_persist, verification_status_to_record).

    - If Apollo returned no email at all → (None, "not_found").
    - If Apollo's status is verified/catchall → keep the email.
    - Anything else (guessed, unverified, bounced) → drop the email but
      record the actual status so the operator sees WHY no email landed.
    """
    if not email_address:
        return None, "not_found"
    status = (raw_status or "").strip().lower()
    if status in ALLOWED_STATUSES:
        return email_address.strip().lower(), status
    return None, status or "unverified"


async def reveal_emails_for_contacts(
    *,
    brand_id: str,
    contact_ids: list[str],
    agency_id: UUID,
    repo: BrandContactRepository,
    apollo_client: ApolloClient | None = None,
    brand_domain: str | None = None,
) -> list[dict[str, Any]]:
    """Reveal Apollo emails for the operator-selected contacts.

    Returns a list of result dicts (one per contact_id, in input order)
    with ``{contact_id, email_revealed (bool), verification_status,
    revealed_at}``. Errors per contact are captured into the result —
    the bulk call never fails on a single Apollo error.
    """
    if not contact_ids:
        return []
    client = apollo_client or ApolloClient()
    results: list[dict[str, Any]] = []

    for contact_id in contact_ids:
        revealed_at = datetime.now(UTC)
        row = await repo.get_by_brand_and_contact(brand_id, contact_id)
        if row is None:
            log.warning("step_5b_contact_missing", brand_id=brand_id, contact_id=contact_id)
            results.append(
                {
                    "contact_id": contact_id,
                    "email_revealed": False,
                    "verification_status": "contact_not_found",
                    "revealed_at": revealed_at.isoformat(),
                }
            )
            continue

        # Linked URL is the primary signal for Apollo's match endpoint.
        # Fall back to (first_name + last_name + domain) where possible
        # so we can still attempt the reveal on web-fallback rows
        # that lack a confirmed LinkedIn URL.
        existing_data = row.data or {}
        linkedin_block = existing_data.get("linkedin") or {}
        linkedin_url = (
            linkedin_block.get("url") if isinstance(linkedin_block, dict) else None
        ) or existing_data.get("linkedin_url")

        try:
            response = await client.match_person(
                linkedin_url=linkedin_url if isinstance(linkedin_url, str) else None,
                organization_domain=brand_domain,
            )
        except Exception as exc:
            log.warning(
                "step_5b_apollo_failed",
                brand_id=brand_id,
                contact_id=contact_id,
                error=str(exc),
            )
            # Still record the attempt so the UI knows we tried.
            await repo.update_email_reveal(
                contact_id,
                email_address=None,
                verification_status="apollo_error",
                revealed_at=revealed_at,
            )
            results.append(
                {
                    "contact_id": contact_id,
                    "email_revealed": False,
                    "verification_status": "apollo_error",
                    "revealed_at": revealed_at.isoformat(),
                }
            )
            continue

        person = (response or {}).get("person") or {}
        raw_email = person.get("email") if isinstance(person, dict) else None
        raw_status = person.get("email_status") if isinstance(person, dict) else None
        email_to_keep, recorded_status = _apply_honesty_floor(
            raw_email if isinstance(raw_email, str) else None,
            raw_status if isinstance(raw_status, str) else None,
        )
        await repo.update_email_reveal(
            contact_id,
            email_address=email_to_keep,
            verification_status=recorded_status,
            revealed_at=revealed_at,
        )
        results.append(
            {
                "contact_id": contact_id,
                "email_revealed": email_to_keep is not None,
                "verification_status": recorded_status,
                "revealed_at": revealed_at.isoformat(),
            }
        )
        log.info(
            "step_5b_email_revealed",
            brand_id=brand_id,
            contact_id=contact_id,
            status=recorded_status,
            email_kept=email_to_keep is not None,
        )

    # Unused agency_id present for symmetry with celery task signature
    # and future per-agency reveal budget tracking; explicit no-op note.
    _ = agency_id
    return results
