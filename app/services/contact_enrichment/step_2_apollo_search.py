"""Step 2 — Apollo employee broad-capture for a brand's marketing team.

For each target_title keyword in the resolved set, hit
``ApolloClient.search_people(domain, titles=[keyword], seniorities)``,
collect distinct people by Apollo ``id``, build ``EnrichedContact``
records.

M8.1 broadens the capture: 12 marketing-adjacent keywords (per
``target_titles.BROAD_TITLE_KEYWORDS``) instead of 5-8 specific titles,
``per_page`` bumped 10 → 100, and the brand-level dedup cap raised
12 → 100. The expensive part of the pipeline (Apollo /people/match
email reveal) does NOT fire here — it fires per-row in the M8.1
Phase C reveal task, only on contacts the operator selects after
seeing the Step 6 ``outreach_recommendation`` badges.

The previous "cost guard" framing no longer applies: Apollo
/people/search has no per-record cost. The 100-candidate cap is now
purely an in-memory safety bound to keep the Step 6 batched Haiku
prompt at sensible token size.
"""

from __future__ import annotations

import re
from typing import Any

from app.services.contact_enrichment._models import EnrichedContact
from app.services.contact_enrichment.target_titles import DEFAULT_SENIORITIES
from app.utils.logging import get_logger
from app.vendors.apollo import ApolloClient

log = get_logger(__name__)


DEFAULT_MAX_CANDIDATES: int = 100
DEFAULT_PER_PAGE: int = 100
_CONTACT_ID_PREFIX = "bc_"


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _build_contact_id(*, brand_id: str, apollo_id: str | None, name: str) -> str:
    """Generate a stable contact_id from Apollo's id + brand + name."""
    base = apollo_id or _slugify(name)
    return f"{_CONTACT_ID_PREFIX}{brand_id}_{base}"[:96]


def _email_from_apollo(person: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pull (email_address, verification_status) from an Apollo person record."""
    email = person.get("email")
    if not isinstance(email, str) or not email.strip():
        return None, None
    # Apollo signals verification status via ``email_status`` field.
    status = person.get("email_status")
    if not isinstance(status, str):
        status = None
    return email.strip().lower(), status


def _location(person: dict[str, Any]) -> dict[str, Any] | None:
    parts = {
        "city": person.get("city"),
        "country": person.get("country"),
        "state": person.get("state"),
    }
    if any(isinstance(v, str) and v for v in parts.values()):
        return {k: v for k, v in parts.items() if isinstance(v, str) and v}
    return None


def _build_contact(*, brand_id: str, person: dict[str, Any], title: str) -> EnrichedContact:
    apollo_id = person.get("id")
    name = (
        person.get("name")
        or " ".join(filter(None, [person.get("first_name"), person.get("last_name")]))
        or "Unknown"
    ).strip()
    email_address, email_status = _email_from_apollo(person)
    contact = EnrichedContact(
        contact_id=_build_contact_id(brand_id=brand_id, apollo_id=apollo_id, name=name),
        brand_id=brand_id,
        name=name,
        title=person.get("title") or title,
        seniority=person.get("seniority"),
        linkedin_url=person.get("linkedin_url"),
        email_address=email_address,
        email_verification_status=email_status,
        location=_location(person),
    )
    contact.add_source(
        step="step_2_apollo_search",
        vendor="apollo",
        payload={"apollo_id": apollo_id, "queried_title": title},
    )
    return contact


async def run(
    *,
    brand_id: str,
    domain: str,
    target_titles: list[str],
    apollo_client: ApolloClient | None = None,
    seniorities: list[str] | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> list[EnrichedContact]:
    """Fan out across target_titles, dedupe by Apollo id, return contacts."""
    if not target_titles or not domain:
        return []
    client = apollo_client or ApolloClient()
    seniority_hints = seniorities or DEFAULT_SENIORITIES

    seen_ids: set[str] = set()
    seen_contact_ids: set[str] = set()
    contacts: list[EnrichedContact] = []

    for title in target_titles:
        if len(contacts) >= max_candidates:
            break
        try:
            response = await client.search_people(
                domain=domain,
                titles=[title],
                seniorities=seniority_hints,
                page=1,
                per_page=DEFAULT_PER_PAGE,
            )
        except Exception as exc:
            log.warning(
                "step_2_apollo_search_failed", brand_id=brand_id, title=title, error=str(exc)
            )
            continue
        people = response.get("people") or []
        if not isinstance(people, list):
            continue
        for person in people:
            if not isinstance(person, dict):
                continue
            apollo_id = person.get("id")
            # Dedupe by Apollo's stable id first; fall back to contact_id slug.
            if isinstance(apollo_id, str) and apollo_id in seen_ids:
                continue
            contact = _build_contact(brand_id=brand_id, person=person, title=title)
            if contact.contact_id in seen_contact_ids:
                continue
            if isinstance(apollo_id, str):
                seen_ids.add(apollo_id)
            seen_contact_ids.add(contact.contact_id)
            contacts.append(contact)
            if len(contacts) >= max_candidates:
                break
    return contacts
