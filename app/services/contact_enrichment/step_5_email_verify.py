"""Step 5 — strict honesty floor on emails.

M8 v0.1 locked decision: surface ONLY emails Apollo verified.
Specifically, keep contacts whose ``email_verification_status`` is one
of ``{"verified", "catchall"}``. Anything else — guessed, unverified,
bounced, missing — has its ``email_address`` blanked. The contact row
still surfaces (LinkedIn outreach is fine without an email), but
downstream email-based pitching ignores it.

No pattern-guessing in v0.1; no Hunter/NeverBounce integration. See
``docs/contact_enrichment_workflow.md`` § "M8 implementation notes".
"""

from __future__ import annotations

from app.services.contact_enrichment._models import EnrichedContact

ALLOWED_STATUSES: frozenset[str] = frozenset({"verified", "catchall"})


def run(*, contacts: list[EnrichedContact]) -> list[EnrichedContact]:
    """Drop email addresses whose Apollo verification status isn't allowed."""
    for c in contacts:
        if not c.email_address:
            continue
        status = (c.email_verification_status or "").strip().lower()
        if status in ALLOWED_STATUSES:
            continue
        # Strict honesty floor — never carry an unverified email forward.
        c.email_address = None
        c.email_verification_status = status or "unknown"
    return contacts
