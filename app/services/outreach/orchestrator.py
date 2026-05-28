"""Phase-3b outreach generation orchestrator.

Single entry point ``generate_enrollment(brand_id, contact_id, talent_id, …)``.
Runs the pipeline:

1. Load talent + contact + brand from repos.
2. Resolve template (caller override > ``select_template(decision_role)``).
3. Run policy filter; early-exit with ``block_reason`` if not eligible.
4. Load the angle library; for each template step:
   a. Filter angles by trigger + role + step number + preferred/excluded categories.
   b. Generate via ``step_generator`` (Opus/Haiku per ``ai_model_override``).
5. Persist a ``PitchEnrollment`` row in ``state="awaiting_approval"``.
6. Append to ``brand_contact.pitch_history[]`` via ``loopback_writers``.

Returns an ``EnrollmentRunResult``. The Celery task wraps this and
handles snapshot writes + retries; the REST trigger is fire-and-forget.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.repositories.brand import BrandRepository
from app.repositories.brand_contact import BrandContactRepository
from app.repositories.pitch_angle import PitchAngleRepository
from app.repositories.pitch_enrollment import PitchEnrollmentRepository
from app.repositories.pitch_template import PitchTemplateRepository
from app.repositories.talent import TalentRepository
from app.services.outreach import (
    angle_filter,
    loopback_writers,
    policy_filter,
    step_generator,
    template_selector,
)
from app.services.outreach._models import (
    EnrollmentDraft,
    EnrollmentRunResult,
    StepGeneration,
)
from app.utils.logging import get_logger

log = get_logger(__name__)


def _new_enrollment_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"enr_{ts}_{uuid.uuid4().hex[:12]}"


def _new_run_id() -> str:
    return f"run_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex[:8]}"


def _talent_dict(row: Any) -> dict[str, Any]:
    return {
        "talent_id": row.talent_id,
        "name": row.name,
        **(dict(row.data or {})),
    }


def _contact_dict(row: Any) -> dict[str, Any]:
    return {
        "contact_id": row.contact_id,
        "brand_id": row.brand_id,
        "name": row.name,
        "decision_role": row.decision_role,
        "email_address": row.email,
        "do_not_contact": row.do_not_contact,
        **(dict(row.data or {})),
    }


def _brand_dict(row: Any) -> dict[str, Any]:
    return {
        "brand_id": row.brand_id,
        "name": row.name,
        "industry_id": row.industry_id,
        "domain": row.domain,
        "hq_country": row.hq_country,
        "company_stage": row.company_stage,
        "typical_campaign_tier": row.typical_campaign_tier,
        **(dict(row.data or {})),
    }


def _step_to_dict(step: StepGeneration) -> dict[str, Any]:
    return {
        "step_number": step.step_number,
        "intent": step.intent,
        "subject": step.subject,
        "body": step.body,
        "angles_used": step.angles_used,
        "personalization_fields_used": step.personalization_fields_used,
        "reasoning": step.reasoning,
        "model_used": step.model_used,
        "timing_offset_days": step.timing_offset_days,
        "validation_warnings": step.validation_warnings,
        "status": "drafted",
    }


async def generate_enrollment(
    *,
    talent_id: str,
    contact_id: str,
    brand_id: str,
    agency_id: UUID,
    template_id: str | None = None,
    talent_repo: TalentRepository,
    contact_repo: BrandContactRepository,
    brand_repo: BrandRepository,
    template_repo: PitchTemplateRepository,
    angle_repo: PitchAngleRepository,
    enrollment_repo: PitchEnrollmentRepository,
) -> EnrollmentRunResult:
    """Generate + persist a fresh enrollment draft."""
    run_id = _new_run_id()
    generated_at = datetime.now(UTC)

    talent = await talent_repo.get_by_talent_id(talent_id)
    contact = await contact_repo.get_by_id(contact_id)
    brand = await brand_repo.get_by_id(brand_id)

    if talent is None or contact is None or brand is None:
        missing = [
            label
            for label, obj in [
                ("talent", talent),
                ("contact", contact),
                ("brand", brand),
            ]
            if obj is None
        ]
        return EnrollmentRunResult(
            talent_id=talent_id,
            contact_id=contact_id,
            brand_id=brand_id,
            run_id=run_id,
            generated_at=generated_at,
            block_reason=f"missing:{','.join(missing)}",
            errors=[f"row not found: {','.join(missing)}"],
        )

    # Template resolution.
    if template_id:
        template = await template_repo.get_by_id(template_id)
        if template is None:
            return EnrollmentRunResult(
                talent_id=talent_id,
                contact_id=contact_id,
                brand_id=brand_id,
                run_id=run_id,
                generated_at=generated_at,
                block_reason=f"unknown_template:{template_id}",
                errors=[f"template {template_id!r} not found"],
            )
    else:
        template = await template_selector.select_template(
            contact.decision_role, repo=template_repo
        )
        if template is None:
            return EnrollmentRunResult(
                talent_id=talent_id,
                contact_id=contact_id,
                brand_id=brand_id,
                run_id=run_id,
                generated_at=generated_at,
                block_reason=f"no_template_for_role:{contact.decision_role}",
            )

    # Policy filter.
    active = await enrollment_repo.find_active_for_contact(contact_id)
    eligible, reason = policy_filter.is_eligible(
        contact=contact,
        talent_id=talent_id,
        active_enrollments=active,
        today=generated_at,
    )
    if not eligible:
        return EnrollmentRunResult(
            talent_id=talent_id,
            contact_id=contact_id,
            brand_id=brand_id,
            run_id=run_id,
            generated_at=generated_at,
            block_reason=reason,
        )

    # Generate per step.
    talent_d = _talent_dict(talent)
    contact_d = _contact_dict(contact)
    brand_d = _brand_dict(brand)
    template_d: dict[str, Any] = dict(template.data or {})
    steps_spec: list[dict[str, Any]] = list(template_d.get("steps") or [])
    if not steps_spec:
        return EnrollmentRunResult(
            talent_id=talent_id,
            contact_id=contact_id,
            brand_id=brand_id,
            run_id=run_id,
            generated_at=generated_at,
            block_reason="template_has_no_steps",
            errors=[f"template {template.template_id} has empty steps[]"],
        )

    angles = await angle_repo.find_all()
    generated_steps: list[StepGeneration] = []
    warnings: list[str] = []

    for step in steps_spec:
        candidates = angle_filter.filter_angles(
            angles=angles,
            talent=talent_d,
            contact=contact_d,
            brand=brand_d,
            step_number=int(step["step_number"]),
            decision_role=contact.decision_role,
            preferred_categories=step.get("preferred_angle_categories") or [],
            excluded_categories=step.get("excluded_angle_categories") or [],
        )
        gen = await step_generator.generate_step(
            talent=talent_d,
            contact=contact_d,
            brand=brand_d,
            step=step,
            template=template_d,
            candidate_angles=candidates,
            previous_steps=list(generated_steps),
        )
        if gen.validation_warnings:
            warnings.extend(f"step{gen.step_number}:{w}" for w in gen.validation_warnings)
        generated_steps.append(gen)

    # Persist as awaiting_approval.
    enrollment_id = _new_enrollment_id()
    data: dict[str, Any] = {
        "steps": [_step_to_dict(s) for s in generated_steps],
        "generation_meta": {
            "run_id": run_id,
            "generated_at": generated_at.isoformat(),
            "template_id": template.template_id,
            "talent_id": talent_id,
            "brand_id": brand_id,
            "contact_id": contact_id,
        },
        "engagement_summary": {
            "sent": 0,
            "delivered": 0,
            "opened": 0,
            "clicked": 0,
            "replied": 0,
            "bounced": 0,
        },
    }
    await enrollment_repo.insert_draft(
        enrollment_id=enrollment_id,
        talent_id=talent_id,
        contact_id=contact_id,
        brand_id=brand_id,
        template_id=template.template_id,
        agency_id=agency_id,
        data=data,
    )
    await loopback_writers.append_pitch_history(
        contact_repo=contact_repo,
        contact_id=contact_id,
        talent_id=talent_id,
        enrollment_id=enrollment_id,
        template_id=template.template_id,
        pitched_at=generated_at,
    )

    draft = EnrollmentDraft(
        enrollment_id=enrollment_id,
        talent_id=talent_id,
        contact_id=contact_id,
        brand_id=brand_id,
        template_id=template.template_id,
        steps=generated_steps,
        sources_summary={
            "angle_count": len(angles),
            "candidate_count_per_step": [
                len(
                    angle_filter.filter_angles(
                        angles=angles,
                        talent=talent_d,
                        contact=contact_d,
                        brand=brand_d,
                        step_number=int(s["step_number"]),
                        decision_role=contact.decision_role,
                        preferred_categories=s.get("preferred_angle_categories") or [],
                        excluded_categories=s.get("excluded_angle_categories") or [],
                    )
                )
                for s in steps_spec
            ],
        },
    )
    return EnrollmentRunResult(
        talent_id=talent_id,
        contact_id=contact_id,
        brand_id=brand_id,
        run_id=run_id,
        generated_at=generated_at,
        draft=draft,
        warnings=warnings,
    )
