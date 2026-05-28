"""Unit tests for ``BrandDealService`` orchestration (with mocked repos)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.errors import BusinessRuleError, ValidationError
from app.models.sqla.brand_deal import BrandDeal
from app.services.brand_deal_service import BrandDealService

_TODAY = datetime.now(UTC).date().isoformat()


def _make_service() -> tuple[BrandDealService, MagicMock, MagicMock, MagicMock]:
    """Helper: build a service with mocked repos."""
    deals = MagicMock()
    talents = MagicMock()
    brands = MagicMock()

    deals.get_by_id = AsyncMock(return_value=None)
    deals.create = AsyncMock(side_effect=lambda inst: inst)
    deals.patch_deal_data = AsyncMock()
    deals.set_outcome_column = AsyncMock()
    deals.set_scalar_columns = AsyncMock()

    talents.get_by_talent_id = AsyncMock()
    talents.patch_data = AsyncMock()

    brands.get_by_id = AsyncMock(return_value=None)
    brands.create_or_skip = AsyncMock()

    return BrandDealService(deals, talents, brands), deals, talents, brands


def _make_talent_row(data: dict[str, Any] | None = None) -> MagicMock:
    row = MagicMock()
    row.data = data or {}
    return row


def _make_valid_payload(**overrides: Any) -> dict[str, Any]:
    payload = {
        "brand_name": "Gymshark",
        "industry_id": "fitness-apparel",
        "campaign_type": "sponsored_post",
        "outcome": "successful",
        "started_at": "2025-09-01",
        "ended_at": "2025-09-15",
        "fee_usd": 5000,
        "kpis": {
            "reach": {
                "value": 1_240_000,
                "source": "platform_verified",
                "as_of": _TODAY,
            }
        },
    }
    payload.update(overrides)
    return payload


# ── create_deal ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unit__create_deal__missing_talent_raises() -> None:
    service, _deals, talents, _brands = _make_service()
    talents.get_by_talent_id.return_value = None
    with pytest.raises(BusinessRuleError, match="not found"):
        await service.create_deal("jane-doe", _make_valid_payload())


@pytest.mark.asyncio
async def test_unit__create_deal__derives_brand_id_from_name() -> None:
    service, deals, talents, _brands = _make_service()
    talents.get_by_talent_id.return_value = _make_talent_row()
    result = await service.create_deal("jane-doe", _make_valid_payload())
    assert result.brand_id == "gymshark"  # slugified from "Gymshark"
    deals.create.assert_awaited()


@pytest.mark.asyncio
async def test_unit__create_deal__honesty_floor_violation_raises() -> None:
    service, _deals, talents, _brands = _make_service()
    talents.get_by_talent_id.return_value = _make_talent_row()
    bad = _make_valid_payload(kpis={"reach": {"value": 100}})  # missing source + as_of
    with pytest.raises(ValidationError):
        await service.create_deal("jane-doe", bad)


@pytest.mark.asyncio
async def test_unit__create_deal__auto_links_existing_previous_brand_by_name() -> None:
    """Light entry `{brand: "Gymshark"}` gets a deal_id back-link on create."""
    service, _deals, talents, _brands = _make_service()
    talents.get_by_talent_id.return_value = _make_talent_row(
        {"previous_brands": [{"brand": "Gymshark", "industry_id": "fitness-apparel"}]}
    )
    await service.create_deal("jane-doe", _make_valid_payload())
    talents.patch_data.assert_awaited_once()
    # The patch_data call carries the updated previous_brands[] list.
    patch_call = talents.patch_data.await_args
    diff = patch_call.args[1]
    assert "previous_brands" in diff
    updated = diff["previous_brands"][0]
    assert updated["deal_id"].startswith("deal_")
    assert updated["brand_id"] == "gymshark"


@pytest.mark.asyncio
async def test_unit__create_deal__no_existing_entry_appends_new_one() -> None:
    """If the brand isn't in previous_brands[], the service appends a new light entry."""
    service, _deals, talents, _brands = _make_service()
    talents.get_by_talent_id.return_value = _make_talent_row({"previous_brands": []})
    await service.create_deal("jane-doe", _make_valid_payload())
    patch_call = talents.patch_data.await_args
    diff = patch_call.args[1]
    new_entries = diff["previous_brands"]
    assert len(new_entries) == 1
    assert new_entries[0]["brand"] == "Gymshark"
    assert new_entries[0]["deal_id"].startswith("deal_")


@pytest.mark.asyncio
async def test_unit__create_deal__derives_deal_id_when_omitted() -> None:
    service, _deals, talents, _brands = _make_service()
    talents.get_by_talent_id.return_value = _make_talent_row()
    result = await service.create_deal("jane-doe", _make_valid_payload())
    assert result.brand_deal_id.startswith("deal_2025_gymshark_")


@pytest.mark.asyncio
async def test_unit__create_deal__honours_caller_supplied_deal_id() -> None:
    service, _deals, talents, _brands = _make_service()
    talents.get_by_talent_id.return_value = _make_talent_row()
    payload = _make_valid_payload(deal_id="deal_2025_gymshark_q4")
    result = await service.create_deal("jane-doe", payload)
    assert result.brand_deal_id == "deal_2025_gymshark_q4"


# ── patch_deal ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unit__patch_deal__missing_deal_raises() -> None:
    service, deals, _talents, _brands = _make_service()
    deals.get_by_id.return_value = None
    with pytest.raises(BusinessRuleError, match="not found"):
        await service.patch_deal("deal_2025_acme_abc", {"outcome": "successful"})


@pytest.mark.asyncio
async def test_unit__patch_deal__server_authoritative_fields_stripped() -> None:
    service, deals, _talents, _brands = _make_service()
    existing = BrandDeal(
        brand_deal_id="deal_2025_acme_abc",
        talent_id="jane-doe",
        brand_id="acme",
        outcome="pending",
        data={
            "deal_id": "deal_2025_acme_abc",
            "brand_id": "acme",
            "industry_id": "consumer-electronics",
            "campaign_type": "sponsored_post",
            "outcome": "pending",
            "first_recorded_at": "2026-01-01T00:00:00Z",
            "last_updated_at": "2026-01-01T00:00:00Z",
        },
    )
    deals.get_by_id.return_value = existing
    deals.patch_deal_data.return_value = existing
    await service.patch_deal(
        "deal_2025_acme_abc",
        {"deal_id": "EVIL", "first_recorded_at": "1999-01-01", "fee_usd": 250},
    )
    sanitised = deals.patch_deal_data.await_args.args[1]
    assert "deal_id" not in sanitised
    assert "first_recorded_at" not in sanitised
    assert sanitised["fee_usd"] == 250


# ── set_outcome ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unit__set_outcome__writes_both_column_and_jsonb() -> None:
    service, deals, _talents, _brands = _make_service()
    fake = BrandDeal(
        brand_deal_id="deal_2025_acme_abc",
        talent_id="jane-doe",
        brand_id="acme",
        outcome="successful",
        data={},
    )
    deals.set_outcome_column.return_value = fake
    deals.patch_deal_data.return_value = fake
    await service.set_outcome("deal_2025_acme_abc", "successful")
    deals.set_outcome_column.assert_awaited_with("deal_2025_acme_abc", "successful")
    deals.patch_deal_data.assert_awaited_with("deal_2025_acme_abc", {"outcome": "successful"})
