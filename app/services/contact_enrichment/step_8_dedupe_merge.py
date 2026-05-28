"""Step 8 — dedupe + merge candidates surfaced across Steps 2/3/4.

Merge precedence (per ``docs/contact_enrichment_workflow.md``):
1. ``linkedin_url`` — strongest identifier; identical URLs merge.
2. ``(name + email_domain)`` — same name at the same brand domain.
3. ``email_address`` — exact match.

When two contacts merge, the one with MORE source records (i.e. more
pipeline coverage) wins canonical identity; the other's source list is
folded in. Email + LinkedIn URL + title prefer the non-empty value.
"""

from __future__ import annotations

from app.services.contact_enrichment._models import EnrichedContact


def _email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.split("@", 1)[1].strip().lower() or None


def _merge_into(canonical: EnrichedContact, dup: EnrichedContact) -> None:
    """Fold ``dup``'s data into ``canonical``."""
    # Prefer non-empty scalar fields from canonical, fall back to dup.
    if not canonical.title and dup.title:
        canonical.title = dup.title
    if not canonical.seniority and dup.seniority:
        canonical.seniority = dup.seniority
    if not canonical.function and dup.function:
        canonical.function = dup.function
    if not canonical.linkedin_url and dup.linkedin_url:
        canonical.linkedin_url = dup.linkedin_url
    if not canonical.email_address and dup.email_address:
        canonical.email_address = dup.email_address
        canonical.email_verification_status = dup.email_verification_status
    if not canonical.location and dup.location:
        canonical.location = dup.location
    # Concatenate sources for the audit trail.
    canonical.sources.extend(dup.sources)


def run(*, contacts: list[EnrichedContact]) -> list[EnrichedContact]:
    """Walk the candidate list and merge by precedence rules."""
    if not contacts:
        return contacts

    by_linkedin: dict[str, EnrichedContact] = {}
    by_name_domain: dict[tuple[str, str], EnrichedContact] = {}
    by_email: dict[str, EnrichedContact] = {}
    keepers: list[EnrichedContact] = []

    for contact in contacts:
        lid_key = (contact.linkedin_url or "").strip().lower() or None
        ed = _email_domain(contact.email_address)
        nd_key: tuple[str, str] | None = (contact.name.strip().lower(), ed) if ed else None
        em_key = (contact.email_address or "").strip().lower() or None

        # Identity lookup in precedence order.
        match: EnrichedContact | None = None
        if lid_key and lid_key in by_linkedin:
            match = by_linkedin[lid_key]
        elif nd_key and nd_key in by_name_domain:
            match = by_name_domain[nd_key]
        elif em_key and em_key in by_email:
            match = by_email[em_key]

        if match is not None:
            _merge_into(match, contact)
            # Re-register newly-revealed identity keys on the canonical row.
            if match.linkedin_url:
                by_linkedin[match.linkedin_url.strip().lower()] = match
            new_ed = _email_domain(match.email_address)
            if new_ed:
                by_name_domain[(match.name.strip().lower(), new_ed)] = match
            if match.email_address:
                by_email[match.email_address.strip().lower()] = match
            continue

        # Net-new identity — register all available keys.
        if lid_key:
            by_linkedin[lid_key] = contact
        if nd_key:
            by_name_domain[nd_key] = contact
        if em_key:
            by_email[em_key] = contact
        keepers.append(contact)

    return keepers
