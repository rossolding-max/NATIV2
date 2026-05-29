"""M11 — verify ``compose_for_discovery_prep`` wires the placeholder fields.

M2 left ``brand_contact`` / ``comparable_brand_deals`` / ``top_pitch_angles`` /
``agency_profile`` as empty stubs. M11's bundle composer must populate them
from the M4/M6/M8/M9 repos. These tests mock the SQLA session + repo classes
so no DB is needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest

from app.agents.bundles import compose_for_discovery_prep

_AGENCY_ID = UUID(int=0)


def _stub_deal() -> MagicMock:
    d = MagicMock()
    d.deal_id = "deal_pipeline_x"
    d.talent_id = "t_riley"
    d.brand_id = "b_lulu"
    d.stage = "lead"
    d.substage = "initial_call_scheduled"
    d.primary_contact_id = "bc_alice"
    d.data = {"lead": {"brief_text": "intro"}}
    return d


def _stub_talent() -> MagicMock:
    t = MagicMock()
    t.talent_id = "t_riley"
    t.name = "Riley Carter"
    t.status = "active"
    t.data = {"niche": "activewear"}
    return t


def _stub_brand() -> MagicMock:
    b = MagicMock()
    b.brand_id = "b_lulu"
    b.name = "Lululemon"
    b.industry_id = "activewear"
    b.data = {"hq": "Vancouver"}
    return b


def _stub_brand_contact(contact_id: str = "bc_alice") -> MagicMock:
    c = MagicMock()
    c.contact_id = contact_id
    c.brand_id = "b_lulu"
    c.name = "Alice Buyer"
    c.decision_role = "buyer"
    c.email = "alice@lulu.com"
    c.do_not_contact = False
    c.data = {"seniority": "director"}
    return c


def _stub_brand_deal(brand_deal_id: str, outcome: str = "completed") -> MagicMock:
    d = MagicMock()
    d.brand_deal_id = brand_deal_id
    d.brand_id = "b_lulu"
    d.talent_id = "t_riley"
    d.outcome = outcome
    d.last_updated_at = None
    d.data = {"campaign_name": brand_deal_id.upper()}
    return d


def _stub_pitch_angle(angle_id: str, score: float) -> MagicMock:
    a = MagicMock()
    a.angle_id = angle_id
    a.category = "credibility"
    a.headline = f"angle headline {angle_id}"
    a.authored_strength_score = score
    return a


def _stub_agency() -> MagicMock:
    p = MagicMock()
    p.name = "Acme Talent"
    p.status = "active"
    p.data = {"colors": {"primary": "#000"}}
    return p


@pytest.mark.asyncio
async def test_unit__compose_dp__wires_agency_profile_from_singleton() -> None:
    session = MagicMock()
    with (
        patch("app.agents.bundles.DealRepository") as mock_deal_repo,
        patch("app.agents.bundles.TalentRepository") as mock_talent_repo,
        patch("app.agents.bundles.BrandRepository") as mock_brand_repo,
        patch("app.agents.bundles.MemoRepository") as mock_memo_repo,
        patch("app.agents.bundles.AgencyProfileRepository") as mock_agency_repo,
        patch("app.agents.bundles.BrandContactRepository") as mock_contact_repo,
        patch("app.agents.bundles.BrandDealRepository") as mock_brand_deal_repo,
        patch("app.agents.bundles.PitchAngleRepository") as mock_pitch_angle_repo,
    ):
        mock_deal_repo.return_value.get_by_id = AsyncMock(return_value=_stub_deal())
        mock_talent_repo.return_value.get_by_id = AsyncMock(return_value=_stub_talent())
        mock_brand_repo.return_value.get_by_id = AsyncMock(return_value=_stub_brand())
        mock_memo_repo.return_value.find_by_tags = AsyncMock(return_value=[])
        mock_agency_repo.return_value.get_singleton = AsyncMock(return_value=_stub_agency())
        mock_contact_repo.return_value.get_by_id = AsyncMock(return_value=_stub_brand_contact())
        mock_brand_deal_repo.return_value.find_by_talent = AsyncMock(return_value=[])
        mock_pitch_angle_repo.return_value.find_all = AsyncMock(return_value=[])

        bundle = await compose_for_discovery_prep(
            session, deal_id="deal_pipeline_x", agency_id=_AGENCY_ID
        )

    assert bundle.agency_profile["name"] == "Acme Talent"
    assert bundle.agency_profile["colors"] == {"primary": "#000"}


@pytest.mark.asyncio
async def test_unit__compose_dp__loads_primary_brand_contact() -> None:
    session = MagicMock()
    with (
        patch("app.agents.bundles.DealRepository") as mock_deal_repo,
        patch("app.agents.bundles.TalentRepository") as mock_talent_repo,
        patch("app.agents.bundles.BrandRepository") as mock_brand_repo,
        patch("app.agents.bundles.MemoRepository") as mock_memo_repo,
        patch("app.agents.bundles.AgencyProfileRepository") as mock_agency_repo,
        patch("app.agents.bundles.BrandContactRepository") as mock_contact_repo,
        patch("app.agents.bundles.BrandDealRepository") as mock_brand_deal_repo,
        patch("app.agents.bundles.PitchAngleRepository") as mock_pitch_angle_repo,
    ):
        mock_deal_repo.return_value.get_by_id = AsyncMock(return_value=_stub_deal())
        mock_talent_repo.return_value.get_by_id = AsyncMock(return_value=_stub_talent())
        mock_brand_repo.return_value.get_by_id = AsyncMock(return_value=_stub_brand())
        mock_memo_repo.return_value.find_by_tags = AsyncMock(return_value=[])
        mock_agency_repo.return_value.get_singleton = AsyncMock(return_value=None)
        mock_contact_repo.return_value.get_by_id = AsyncMock(return_value=_stub_brand_contact())
        mock_brand_deal_repo.return_value.find_by_talent = AsyncMock(return_value=[])
        mock_pitch_angle_repo.return_value.find_all = AsyncMock(return_value=[])

        bundle = await compose_for_discovery_prep(
            session, deal_id="deal_pipeline_x", agency_id=_AGENCY_ID
        )

    assert bundle.brand_contact is not None
    assert bundle.brand_contact["contact_id"] == "bc_alice"
    assert bundle.brand_contact["seniority"] == "director"  # merged from data


@pytest.mark.asyncio
async def test_unit__compose_dp__falls_back_to_first_brand_contact_when_primary_missing() -> None:
    session = MagicMock()
    deal = _stub_deal()
    deal.primary_contact_id = None  # No primary specified.
    with (
        patch("app.agents.bundles.DealRepository") as mock_deal_repo,
        patch("app.agents.bundles.TalentRepository") as mock_talent_repo,
        patch("app.agents.bundles.BrandRepository") as mock_brand_repo,
        patch("app.agents.bundles.MemoRepository") as mock_memo_repo,
        patch("app.agents.bundles.AgencyProfileRepository") as mock_agency_repo,
        patch("app.agents.bundles.BrandContactRepository") as mock_contact_repo,
        patch("app.agents.bundles.BrandDealRepository") as mock_brand_deal_repo,
        patch("app.agents.bundles.PitchAngleRepository") as mock_pitch_angle_repo,
    ):
        mock_deal_repo.return_value.get_by_id = AsyncMock(return_value=deal)
        mock_talent_repo.return_value.get_by_id = AsyncMock(return_value=_stub_talent())
        mock_brand_repo.return_value.get_by_id = AsyncMock(return_value=_stub_brand())
        mock_memo_repo.return_value.find_by_tags = AsyncMock(return_value=[])
        mock_agency_repo.return_value.get_singleton = AsyncMock(return_value=None)
        mock_contact_repo.return_value.get_by_id = AsyncMock(return_value=None)
        mock_contact_repo.return_value.find_by_brand = AsyncMock(
            return_value=[_stub_brand_contact("bc_fallback")]
        )
        mock_brand_deal_repo.return_value.find_by_talent = AsyncMock(return_value=[])
        mock_pitch_angle_repo.return_value.find_all = AsyncMock(return_value=[])

        bundle = await compose_for_discovery_prep(
            session, deal_id="deal_pipeline_x", agency_id=_AGENCY_ID
        )

    assert bundle.brand_contact is not None
    assert bundle.brand_contact["contact_id"] == "bc_fallback"


@pytest.mark.asyncio
async def test_unit__compose_dp__caps_comparable_brand_deals_at_5() -> None:
    session = MagicMock()
    seven_deals = [_stub_brand_deal(f"bd_{i}") for i in range(7)]
    with (
        patch("app.agents.bundles.DealRepository") as mock_deal_repo,
        patch("app.agents.bundles.TalentRepository") as mock_talent_repo,
        patch("app.agents.bundles.BrandRepository") as mock_brand_repo,
        patch("app.agents.bundles.MemoRepository") as mock_memo_repo,
        patch("app.agents.bundles.AgencyProfileRepository") as mock_agency_repo,
        patch("app.agents.bundles.BrandContactRepository") as mock_contact_repo,
        patch("app.agents.bundles.BrandDealRepository") as mock_brand_deal_repo,
        patch("app.agents.bundles.PitchAngleRepository") as mock_pitch_angle_repo,
    ):
        mock_deal_repo.return_value.get_by_id = AsyncMock(return_value=_stub_deal())
        mock_talent_repo.return_value.get_by_id = AsyncMock(return_value=_stub_talent())
        mock_brand_repo.return_value.get_by_id = AsyncMock(return_value=_stub_brand())
        mock_memo_repo.return_value.find_by_tags = AsyncMock(return_value=[])
        mock_agency_repo.return_value.get_singleton = AsyncMock(return_value=None)
        mock_contact_repo.return_value.get_by_id = AsyncMock(return_value=_stub_brand_contact())
        mock_brand_deal_repo.return_value.find_by_talent = AsyncMock(return_value=seven_deals)
        mock_pitch_angle_repo.return_value.find_all = AsyncMock(return_value=[])

        bundle = await compose_for_discovery_prep(
            session, deal_id="deal_pipeline_x", agency_id=_AGENCY_ID
        )

    assert len(bundle.comparable_brand_deals) == 5
    ids = {d["brand_deal_id"] for d in bundle.comparable_brand_deals}
    assert ids == {f"bd_{i}" for i in range(5)}


@pytest.mark.asyncio
async def test_unit__compose_dp__caps_top_pitch_angles_at_5() -> None:
    session = MagicMock()
    ten_angles = [_stub_pitch_angle(f"ang_{i}", 0.9 - i * 0.05) for i in range(10)]
    with (
        patch("app.agents.bundles.DealRepository") as mock_deal_repo,
        patch("app.agents.bundles.TalentRepository") as mock_talent_repo,
        patch("app.agents.bundles.BrandRepository") as mock_brand_repo,
        patch("app.agents.bundles.MemoRepository") as mock_memo_repo,
        patch("app.agents.bundles.AgencyProfileRepository") as mock_agency_repo,
        patch("app.agents.bundles.BrandContactRepository") as mock_contact_repo,
        patch("app.agents.bundles.BrandDealRepository") as mock_brand_deal_repo,
        patch("app.agents.bundles.PitchAngleRepository") as mock_pitch_angle_repo,
    ):
        mock_deal_repo.return_value.get_by_id = AsyncMock(return_value=_stub_deal())
        mock_talent_repo.return_value.get_by_id = AsyncMock(return_value=_stub_talent())
        mock_brand_repo.return_value.get_by_id = AsyncMock(return_value=_stub_brand())
        mock_memo_repo.return_value.find_by_tags = AsyncMock(return_value=[])
        mock_agency_repo.return_value.get_singleton = AsyncMock(return_value=None)
        mock_contact_repo.return_value.get_by_id = AsyncMock(return_value=_stub_brand_contact())
        mock_brand_deal_repo.return_value.find_by_talent = AsyncMock(return_value=[])
        mock_pitch_angle_repo.return_value.find_all = AsyncMock(return_value=ten_angles)

        bundle = await compose_for_discovery_prep(
            session, deal_id="deal_pipeline_x", agency_id=_AGENCY_ID
        )

    assert len(bundle.top_pitch_angles) == 5
    # The repo orders by authored_strength_score desc; we should take the top 5.
    assert bundle.top_pitch_angles[0]["angle_id"] == "ang_0"
    assert bundle.top_pitch_angles[-1]["angle_id"] == "ang_4"
