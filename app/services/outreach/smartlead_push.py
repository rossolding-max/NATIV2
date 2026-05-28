"""Push an approved enrollment to Smartlead.

For each (talent, template) pair, create-or-find a Smartlead campaign
named ``f"{talent_id}::{template_id}"``, add the contact as a lead,
push the full step sequence. Returns the smartlead_meta dict that
gets persisted on the enrollment row.
"""

from __future__ import annotations

from typing import Any

from app.utils.logging import get_logger
from app.vendors.smartlead import SmartleadClient

log = get_logger(__name__)


def _campaign_name(*, talent_id: str, template_id: str) -> str:
    return f"{talent_id}::{template_id}"


async def _find_or_create_campaign(
    *,
    smartlead_client: SmartleadClient,
    talent_id: str,
    template_id: str,
    campaign_id_hint: str | None = None,
) -> str:
    """Re-use a known campaign id when the caller has one; otherwise create.

    The Smartlead REST surface doesn't expose a name->id lookup; we cache
    the campaign_id on the enrollment row's ``smartlead_meta`` after the
    first push so subsequent pushes for the same (talent, template)
    pair short-circuit straight to the cached id.
    """
    if campaign_id_hint:
        return campaign_id_hint
    response = await smartlead_client.create_campaign(
        name=_campaign_name(talent_id=talent_id, template_id=template_id)
    )
    campaign_id = response.get("id") or response.get("campaign_id")
    if not isinstance(campaign_id, str) and not isinstance(campaign_id, int):
        raise RuntimeError(f"smartlead create_campaign returned no id; response={response!r}")
    return str(campaign_id)


def _lead_payload(
    *,
    enrollment_id: str,
    contact: dict[str, Any],
    brand: dict[str, Any],
    primary_angle: str | None,
) -> dict[str, Any]:
    name = (contact.get("name") or "").strip()
    first = name.split(" ", 1)[0] if name else ""
    last = name.split(" ", 1)[1] if " " in name else ""
    return {
        "email": contact.get("email_address") or contact.get("email"),
        "first_name": first,
        "last_name": last,
        "company_name": brand.get("name"),
        "custom_fields": {
            "enrollment_id": enrollment_id,
            "decision_role": contact.get("decision_role"),
            "primary_angle": primary_angle or "",
        },
    }


def _sequence_payloads(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert enrollment.data.steps[] into Smartlead's per-step sequence shape."""
    out: list[dict[str, Any]] = []
    for s in steps:
        out.append(
            {
                "seq_number": int(s.get("step_number") or 1),
                "seq_delay_details": {
                    "delay_in_days": int(s.get("timing_offset_days") or 0),
                },
                "subject": s.get("subject") or "",
                "email_body": s.get("body") or "",
            }
        )
    return out


async def push_to_smartlead(
    *,
    enrollment_id: str,
    talent_id: str,
    template_id: str,
    contact: dict[str, Any],
    brand: dict[str, Any],
    steps: list[dict[str, Any]],
    smartlead_client: SmartleadClient,
    campaign_id_hint: str | None = None,
) -> dict[str, Any]:
    """Push the approved enrollment to Smartlead. Returns smartlead_meta."""
    if not contact.get("email_address") and not contact.get("email"):
        raise RuntimeError("cannot push enrollment without a verified contact email")

    campaign_id = await _find_or_create_campaign(
        smartlead_client=smartlead_client,
        talent_id=talent_id,
        template_id=template_id,
        campaign_id_hint=campaign_id_hint,
    )

    primary_angle = None
    if steps:
        primary_angle = (steps[0].get("angles_used") or {}).get("primary")
    lead_resp = await smartlead_client.add_leads(
        campaign_id,
        [
            _lead_payload(
                enrollment_id=enrollment_id,
                contact=contact,
                brand=brand,
                primary_angle=primary_angle,
            )
        ],
    )
    lead_id = (
        lead_resp.get("lead_id")
        or lead_resp.get("id")
        or (lead_resp.get("leads") or [{}])[0].get("lead_id")
    )

    await smartlead_client.add_sequence(campaign_id, _sequence_payloads(steps))

    meta: dict[str, Any] = {
        "campaign_id": str(campaign_id),
        "lead_id": str(lead_id) if lead_id is not None else None,
        "campaign_name": _campaign_name(talent_id=talent_id, template_id=template_id),
    }
    log.info(
        "outreach_smartlead_push_complete",
        enrollment_id=enrollment_id,
        campaign_id=meta["campaign_id"],
        lead_id=meta["lead_id"],
    )
    return meta
