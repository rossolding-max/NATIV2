"""Per-step LLM generation for outreach emails.

For each step in a template, build the system prompt + context bundle
+ applicable angles, call Claude (Opus 4.7 for step 1, Haiku 4.5 for
steps 2+), parse the JSON-only response, validate against the
template's guardrails. Up to 3 regenerations on validation failure;
on permanent failure raise + the orchestrator records the warning.

Mirrors the M8 / M7-Search-13 batched-LLM pattern: tolerant JSON
parser (code-fence stripping + regex fallback), explicit JSON schema in
the prompt, fail-soft on transient LLM errors.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.outreach._models import StepGeneration
from app.utils.logging import get_logger

log = get_logger(__name__)


_DEFAULT_MAX_BODY_CHARS: int = 600
_DEFAULT_MAX_SUBJECT_CHARS: int = 60
_DEFAULT_MAX_RETRIES: int = 3

_BANNED_PHRASES: tuple[str, ...] = (
    # Catch the most common LLM tells; expand as we see them in real output.
    "as an ai language model",
    "i hope this email finds you well",
    "quick question",
    "circling back",
    "just checking in",
)


def _build_prompt(
    *,
    talent: dict[str, Any],
    contact: dict[str, Any],
    brand: dict[str, Any],
    step: dict[str, Any],
    template: dict[str, Any],
    candidate_angles: list[dict[str, Any]],
    previous_steps: list[StepGeneration],
) -> str:
    """Build the system+user prompt for one step.

    Returns a single string; the orchestrator passes it as the only
    message to Claude (no separate system role per the existing M8
    pattern in ``search_13_values_aligned.py``).
    """
    guardrails = template.get("guardrails") or {}
    tone = guardrails.get("tone") or "direct_professional"
    max_body = guardrails.get("max_body_chars", _DEFAULT_MAX_BODY_CHARS)
    max_subject = guardrails.get("max_subject_chars", _DEFAULT_MAX_SUBJECT_CHARS)
    require_unsub = guardrails.get("require_can_spam_unsubscribe", True)

    angles_block = (
        "\n".join(
            f"  - {c['angle'].angle_id} [{c['angle'].category}, strength={c['score']:.2f}]: "
            f"{(c['angle'].data or {}).get('example_phrasing') or c['angle'].name}"
            + (f" | merge_fields={c['merge_fields']}" if c["merge_fields"] else "")
            for c in candidate_angles
        )
        or "  (no applicable angles — write a generic, low-pressure intro)"
    )

    prev_block = ""
    if previous_steps:
        prev_block = "\nPrevious step subjects/bodies (do NOT repeat angle or phrasing):\n"
        for ps in previous_steps:
            prev_block += f"  - Step {ps.step_number} subject: {ps.subject}\n"

    top_countries = [
        c if isinstance(c, str) else c.get("country")
        for c in (talent.get("audience_demographics") or {}).get("top_countries") or []
    ]
    email_addr = contact.get("email_address") or ""
    email_domain = email_addr.split("@")[-1] if email_addr else "unknown"
    return f"""You are drafting a single outreach email for a talent agency.

Talent: {talent.get("name", "Unknown")}
  - bio: {(talent.get("bio") or "")[:200]}
  - content_niches: {talent.get("content_niches", [])}
  - top_countries: {top_countries}

Contact: {contact.get("name", "Unknown")} ({contact.get("decision_role", "unknown")})
  - title: {contact.get("title") or "unknown"}
  - email_domain: {email_domain}

Brand: {brand.get("name", "Unknown")}
  - industry: {brand.get("industry_id") or "unknown"}
  - hq_country: {brand.get("hq_country") or "unknown"}

Step:
  - step_number: {step["step_number"]}
  - intent: {step["intent"]}
  - tone: {tone}
  - max_subject_chars: {max_subject}
  - max_body_chars: {max_body}
  - require_can_spam_unsubscribe: {require_unsub}

Candidate angles (use 1 primary; optionally 1 supporting):
{angles_block}
{prev_block}
Respond with JSON ONLY in this exact format (no prose, no markdown
fences):
{{
  "subject": "...",
  "body": "...",
  "angles_used": {{"primary": "<angle_id>", "supporting": null}},
  "personalization_fields_used": ["contact.name", "..."],
  "reasoning": "one sentence"
}}
"""


def _parse_response(text: str) -> dict[str, Any] | None:
    """Tolerant JSON extraction — code-fence stripping + regex fallback."""
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s)
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return data if isinstance(data, dict) else None


def _validate(
    parsed: dict[str, Any],
    *,
    template: dict[str, Any],
    candidate_angle_ids: set[str],
) -> tuple[bool, list[str]]:
    """Return (ok, list_of_warnings_or_errors)."""
    issues: list[str] = []
    subject = (parsed.get("subject") or "").strip()
    body = (parsed.get("body") or "").strip()
    guardrails = template.get("guardrails") or {}
    max_subject = guardrails.get("max_subject_chars", _DEFAULT_MAX_SUBJECT_CHARS)
    max_body = guardrails.get("max_body_chars", _DEFAULT_MAX_BODY_CHARS)

    if not subject:
        issues.append("subject_empty")
    elif len(subject) > max_subject:
        issues.append(f"subject_too_long:{len(subject)}>{max_subject}")
    if not body:
        issues.append("body_empty")
    elif len(body) > max_body:
        issues.append(f"body_too_long:{len(body)}>{max_body}")

    angles_used = parsed.get("angles_used") or {}
    primary = angles_used.get("primary") if isinstance(angles_used, dict) else None
    if primary and primary not in candidate_angle_ids:
        issues.append(f"angle_not_in_candidates:{primary}")
    supporting = angles_used.get("supporting") if isinstance(angles_used, dict) else None
    if supporting and supporting not in candidate_angle_ids:
        issues.append(f"supporting_angle_not_in_candidates:{supporting}")

    lower = body.lower()
    for phrase in _BANNED_PHRASES:
        if phrase in lower:
            issues.append(f"banned_phrase:{phrase}")

    return (not issues, issues)


async def generate_step(
    *,
    talent: dict[str, Any],
    contact: dict[str, Any],
    brand: dict[str, Any],
    step: dict[str, Any],
    template: dict[str, Any],
    candidate_angles: list[dict[str, Any]],
    previous_steps: list[StepGeneration] | None = None,
    max_retries: int = _DEFAULT_MAX_RETRIES,
) -> StepGeneration:
    """Generate one step. Fail-soft to a placeholder ``StepGeneration``
    with ``validation_warnings`` populated on permanent failure.
    """
    from app.agents.llm_client import get_async_anthropic
    from app.config import settings

    model = (step.get("ai_model_override") or "").strip() or settings.anthropic_default_model
    prev = previous_steps or []
    prompt = _build_prompt(
        talent=talent,
        contact=contact,
        brand=brand,
        step=step,
        template=template,
        candidate_angles=candidate_angles,
        previous_steps=prev,
    )
    candidate_ids = {c["angle"].angle_id for c in candidate_angles}
    client = get_async_anthropic()

    last_warnings: list[str] = []
    parsed: dict[str, Any] | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.messages.create(
                model=model,
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            log.warning(
                "step_generation_llm_error",
                step_number=step.get("step_number"),
                attempt=attempt,
                error=str(exc),
            )
            last_warnings = [f"llm_error:{exc}"]
            continue
        text_parts: list[str] = []
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                text_parts.append(getattr(block, "text", "") or "")
        parsed = _parse_response("".join(text_parts))
        if parsed is None:
            last_warnings = ["unparseable_json"]
            continue
        ok, issues = _validate(parsed, template=template, candidate_angle_ids=candidate_ids)
        last_warnings = issues
        if ok:
            break

    if parsed is None:
        return StepGeneration(
            step_number=int(step["step_number"]),
            intent=str(step.get("intent") or ""),
            subject="",
            body="",
            timing_offset_days=int(step.get("timing_offset_days") or 0),
            validation_warnings=last_warnings or ["llm_failure"],
            model_used=model,
        )

    angles_used = parsed.get("angles_used") or {}
    if not isinstance(angles_used, dict):
        angles_used = {}
    personalization = parsed.get("personalization_fields_used") or []
    if not isinstance(personalization, list):
        personalization = []

    return StepGeneration(
        step_number=int(step["step_number"]),
        intent=str(step.get("intent") or ""),
        subject=str(parsed.get("subject") or ""),
        body=str(parsed.get("body") or ""),
        angles_used={
            "primary": angles_used.get("primary"),
            "supporting": angles_used.get("supporting"),
        },
        personalization_fields_used=[str(p) for p in personalization],
        reasoning=str(parsed.get("reasoning") or ""),
        model_used=model,
        timing_offset_days=int(step.get("timing_offset_days") or 0),
        validation_warnings=last_warnings,
    )
