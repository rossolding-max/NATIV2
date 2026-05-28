"""Step 3 — LinkedIn profile enrichment for Apollo hits.

For each Apollo-surfaced contact with a ``linkedin_url``, hit
``LinkedInScraperClient.get_profile_by_url`` and merge useful fields
(headline, current_company, education, location) into the contact's
sources block. We do NOT overwrite Apollo-provided fields — LinkedIn
data lands under a ``linkedin.profile_data`` sub-key for audit.

For contacts WITHOUT a LinkedIn URL, this step is a no-op; Step 4 (Exa
web fallback) catches them if the title was important enough.
"""

from __future__ import annotations

from typing import Any

from app.services.contact_enrichment._models import EnrichedContact
from app.utils.logging import get_logger
from app.vendors.linkedin import LinkedInScraperClient

log = get_logger(__name__)


async def run(
    *,
    contacts: list[EnrichedContact],
    linkedin_client: LinkedInScraperClient | None = None,
) -> list[EnrichedContact]:
    """Enrich each contact that has a ``linkedin_url`` with profile detail."""
    if not contacts:
        return contacts
    enrichable = [c for c in contacts if c.linkedin_url]
    if not enrichable:
        return contacts
    client = linkedin_client or LinkedInScraperClient()

    for contact in enrichable:
        try:
            profile = await client.get_profile_by_url(contact.linkedin_url or "")
        except Exception as exc:
            log.warning(
                "step_3_linkedin_failed",
                contact_id=contact.contact_id,
                linkedin_url=contact.linkedin_url,
                error=str(exc),
            )
            continue
        if not isinstance(profile, dict):
            continue
        # Backfill any missing scalar fields from LinkedIn (don't overwrite
        # Apollo's already-populated values — Apollo is the canonical
        # source for title/email/seniority).
        if not contact.title and isinstance(profile.get("headline"), str):
            contact.title = profile["headline"]
        if not contact.location:
            loc = profile.get("location")
            if isinstance(loc, dict):
                contact.location = loc
            elif isinstance(loc, str):
                contact.location = {"city": loc}
        contact.add_source(
            step="step_3_linkedin_enrich",
            vendor="linkedin",
            payload={"profile_summary": _profile_summary(profile)},
        )
    return contacts


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    """Keep only the audit-relevant slice — full payload bloats JSONB rows."""
    keep_keys = ("headline", "location", "current_company", "experiences", "education")
    return {k: profile[k] for k in keep_keys if k in profile}
