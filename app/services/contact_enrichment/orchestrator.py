"""Per-brand contact-enrichment orchestrator.

Single entry point ``run_enrichment(brand_id, *, talent_id=None,
target_titles=None, brand_metadata=None)``. Runs the Phase A pipeline
(2 → 3 → 4 → 6 → 8 → qualification → policy filter), returns an
``EnrichmentRunResult``.

M8.1: Step 5 (email verify) is no longer in the Phase A chain. Apollo
``/people/search`` returns no emails, and we no longer pre-emptively
call Apollo ``/people/match`` for everyone. Email reveal fires
per-row in the Phase C reveal task (``contact_email_reveal_task.py``)
triggered by the operator selecting contacts. The strict honesty-floor
logic that used to live in ``step_5_email_verify`` now lives in
``step_5b_reveal_email`` and applies at per-row reveal time.

Pure — no DB writes. The Celery task body
(``contact_enrichment_task.py``) does the ``upsert_run_batch`` +
``write_snapshot`` calls.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.services.contact_enrichment import (
    policy_filter,
    qualification,
    step_2_apollo_search,
    step_3_linkedin_enrich,
    step_4_web_fallback,
    step_6_decision_role,
    step_8_dedupe_merge,
)
from app.services.contact_enrichment._models import (
    EnrichedContact,
    EnrichmentRunResult,
)
from app.services.contact_enrichment.target_titles import resolve_target_titles
from app.utils.logging import get_logger

log = get_logger(__name__)


def _new_run_id() -> str:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"enrich_{ts}_{uuid.uuid4().hex[:8]}"


async def run_enrichment(
    *,
    brand_id: str,
    brand_metadata: dict[str, Any],
    talent_id: str | None = None,
    target_titles: list[str] | None = None,
    seniorities: list[str] | None = None,
    existing_workflow: dict[str, dict[str, Any]] | None = None,
    qualification_threshold: float = 0.30,
    apollo_client: Any = None,
    linkedin_client: Any = None,
) -> EnrichmentRunResult:
    """Run the 9-step enrichment pipeline for one brand.

    ``brand_metadata`` is expected to carry at least ``name`` + ``domain``
    plus any seed-map enrichment fields (``industry_id``, ``revenue``,
    ``headcount``, ``typical_campaign_tier``, ``company_stage``).
    """
    errors: list[str] = []
    steps_run: list[str] = []
    run_id = _new_run_id()
    generated_at = datetime.now(UTC)

    domain = brand_metadata.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        return EnrichmentRunResult(
            brand_id=brand_id,
            run_id=run_id,
            generated_at=generated_at,
            contacts=[],
            blocked=[],
            errors=["brand has no domain — Apollo lookup impossible"],
            steps_run=[],
            talent_id=talent_id,
        )

    titles = resolve_target_titles(caller_supplied=target_titles)

    # Step 2 — Apollo employee search.
    contacts: list[EnrichedContact] = []
    try:
        contacts = await step_2_apollo_search.run(
            brand_id=brand_id,
            domain=domain,
            target_titles=titles,
            apollo_client=apollo_client,
            seniorities=seniorities,
        )
        steps_run.append("step_2_apollo_search")
    except Exception as exc:
        log.warning("step_2_failed", brand_id=brand_id, error=str(exc))
        errors.append(f"step_2_apollo_search: {exc!s}")

    # Step 3 — LinkedIn profile enrichment for Apollo hits.
    if contacts:
        try:
            contacts = await step_3_linkedin_enrich.run(
                contacts=contacts, linkedin_client=linkedin_client
            )
            steps_run.append("step_3_linkedin_enrich")
        except Exception as exc:
            log.warning("step_3_failed", brand_id=brand_id, error=str(exc))
            errors.append(f"step_3_linkedin_enrich: {exc!s}")

    # Step 4 — Exa web-search fallback for unfilled titles.
    try:
        new_via_web = await step_4_web_fallback.run(
            brand_id=brand_id,
            brand_name=brand_metadata.get("name") or brand_id,
            target_titles=titles,
            already_filled=contacts,
        )
        if new_via_web:
            contacts.extend(new_via_web)
        steps_run.append("step_4_web_fallback")
    except Exception as exc:
        log.warning("step_4_failed", brand_id=brand_id, error=str(exc))
        errors.append(f"step_4_web_fallback: {exc!s}")

    # Step 5 SKIPPED in Phase A (M8.1). Apollo /people/search returns no
    # emails; the strict honesty floor moves to step_5b_reveal_email,
    # triggered per-row by the operator in Phase C.

    # Step 6 — Claude decision_role + outreach_recommendation classifier
    # (one batched call).
    if contacts:
        try:
            contacts = await step_6_decision_role.run(
                contacts=contacts, brand_metadata=brand_metadata
            )
            steps_run.append("step_6_decision_role")
        except Exception as exc:
            log.warning("step_6_failed", brand_id=brand_id, error=str(exc))
            errors.append(f"step_6_decision_role: {exc!s}")

    # Step 8 — dedupe + merge.
    contacts = step_8_dedupe_merge.run(contacts=contacts)
    steps_run.append("step_8_dedupe_merge")

    # Step 9 — qualification + policy filter.
    qualified = [qualification.qualify_contact(c) for c in contacts]
    kept, blocked = policy_filter.apply_contact_filters(
        qualified,
        existing_workflow=existing_workflow,
        talent_id=talent_id,
        qualification_threshold=qualification_threshold,
    )

    return EnrichmentRunResult(
        brand_id=brand_id,
        run_id=run_id,
        generated_at=generated_at,
        contacts=kept,
        blocked=blocked,
        errors=errors,
        steps_run=steps_run,
        talent_id=talent_id,
    )
