"""Phase 3b — multi-step outreach generation + reply handling.

Reads M8's qualified ``brand_contact`` roster + M7's brand_candidates,
generates 2-4 step AI sequences per (talent, contact, template), pushes
to Smartlead, classifies replies, and creates Phase-4 deals on
``interested``.

Trigger: manual REST in v0.1 (``settings.outreach_auto_enroll = False``).
Auto-fire from M8 enrichment defers to M9.1.
"""

from app.services.outreach._models import (
    EnrollmentDraft,
    EnrollmentRunResult,
    StepGeneration,
)

__all__ = ["EnrollmentDraft", "EnrollmentRunResult", "StepGeneration"]
