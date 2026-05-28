"""Smartlead push wrapper — create campaign + add lead + push sequences."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.outreach import smartlead_push


@pytest.mark.asyncio
async def test_unit__smartlead_push__happy_path_creates_and_pushes() -> None:
    smartlead = MagicMock()
    smartlead.create_campaign = AsyncMock(return_value={"id": 12345})
    smartlead.add_leads = AsyncMock(return_value={"lead_id": 999})
    smartlead.add_sequence = AsyncMock(return_value={"ok": True})

    meta = await smartlead_push.push_to_smartlead(
        enrollment_id="enr_42",
        talent_id="jane-fitstar",
        template_id="buyer-direct-pitch",
        contact={
            "name": "Alice Smith",
            "email_address": "alice@brand.com",
            "decision_role": "buyer",
        },
        brand={"name": "Lululemon"},
        steps=[
            {
                "step_number": 1,
                "timing_offset_days": 0,
                "subject": "Quick intro",
                "body": "Hi Alice...",
                "angles_used": {"primary": "comp_proof"},
            }
        ],
        smartlead_client=smartlead,
    )
    assert meta["campaign_id"] == "12345"
    assert meta["lead_id"] == "999"
    assert meta["campaign_name"] == "jane-fitstar::buyer-direct-pitch"
    smartlead.create_campaign.assert_awaited_once()
    smartlead.add_leads.assert_awaited_once()
    smartlead.add_sequence.assert_awaited_once()


@pytest.mark.asyncio
async def test_unit__smartlead_push__campaign_id_hint_skips_create() -> None:
    smartlead = MagicMock()
    smartlead.create_campaign = AsyncMock()
    smartlead.add_leads = AsyncMock(return_value={"lead_id": "L1"})
    smartlead.add_sequence = AsyncMock()
    await smartlead_push.push_to_smartlead(
        enrollment_id="enr_42",
        talent_id="t",
        template_id="x",
        contact={"name": "A B", "email_address": "a@b.com"},
        brand={"name": "B"},
        steps=[{"step_number": 1, "subject": "s", "body": "b"}],
        smartlead_client=smartlead,
        campaign_id_hint="existing_42",
    )
    smartlead.create_campaign.assert_not_called()
    smartlead.add_leads.assert_awaited_once()
    args, _ = smartlead.add_leads.call_args
    assert args[0] == "existing_42"


@pytest.mark.asyncio
async def test_unit__smartlead_push__missing_email_raises() -> None:
    smartlead = MagicMock()
    with pytest.raises(RuntimeError, match="verified contact email"):
        await smartlead_push.push_to_smartlead(
            enrollment_id="enr_42",
            talent_id="t",
            template_id="x",
            contact={"name": "A"},  # no email
            brand={"name": "B"},
            steps=[],
            smartlead_client=smartlead,
        )


@pytest.mark.asyncio
async def test_unit__smartlead_push__create_campaign_no_id_raises() -> None:
    smartlead = MagicMock()
    smartlead.create_campaign = AsyncMock(return_value={"oops": "no id"})
    with pytest.raises(RuntimeError, match="no id"):
        await smartlead_push.push_to_smartlead(
            enrollment_id="enr_42",
            talent_id="t",
            template_id="x",
            contact={"email_address": "a@b.com", "name": "A B"},
            brand={"name": "B"},
            steps=[{"step_number": 1, "subject": "s", "body": "b"}],
            smartlead_client=smartlead,
        )


@pytest.mark.asyncio
async def test_unit__smartlead_push__lead_payload_includes_custom_fields() -> None:
    smartlead = MagicMock()
    smartlead.create_campaign = AsyncMock(return_value={"id": "C"})
    smartlead.add_leads = AsyncMock(return_value={"lead_id": "L"})
    smartlead.add_sequence = AsyncMock()
    await smartlead_push.push_to_smartlead(
        enrollment_id="enr_42",
        talent_id="t",
        template_id="buyer-direct-pitch",
        contact={
            "name": "Alice Smith",
            "email_address": "alice@brand.com",
            "decision_role": "buyer",
        },
        brand={"name": "Lululemon"},
        steps=[
            {
                "step_number": 1,
                "subject": "S",
                "body": "B",
                "angles_used": {"primary": "comp_proof"},
            }
        ],
        smartlead_client=smartlead,
    )
    args, _ = smartlead.add_leads.call_args
    leads = args[1]
    assert leads[0]["custom_fields"]["enrollment_id"] == "enr_42"
    assert leads[0]["custom_fields"]["primary_angle"] == "comp_proof"
    assert leads[0]["first_name"] == "Alice"
    assert leads[0]["last_name"] == "Smith"
