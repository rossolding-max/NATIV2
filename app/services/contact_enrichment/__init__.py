"""Phase 3a — per-brand contact enrichment pipeline.

Builds a vetted ``brand_contact`` roster for each brand surfaced by M7's
discovery pipeline. M8 ships the 9-step pipeline per
``docs/contact_enrichment_workflow.md``: Apollo employee search →
LinkedIn profile enrichment → Exa web-search fallback → Apollo SMTP
email verification → Claude ``decision_role`` classifier → dedupe →
qualification scoring → policy filter (DNC + 14-day per-talent
cooldown).

Trigger: manual only (``POST /api/v1/brands/{brand_id}/contact-enrichment/run``).
Auto-fire from M7's snapshot writer defers to M8.1.
"""

from app.services.contact_enrichment._models import (
    EnrichedContact,
    EnrichmentRunResult,
    QualifiedContact,
)

__all__ = ["EnrichedContact", "EnrichmentRunResult", "QualifiedContact"]
