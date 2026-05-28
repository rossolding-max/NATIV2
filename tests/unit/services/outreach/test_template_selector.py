"""Template selector — decision_role → PitchTemplate routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.outreach import template_selector


@pytest.mark.asyncio
async def test_unit__template_selector__buyer_returns_template() -> None:
    template = MagicMock()
    template.template_id = "buyer-direct-pitch"
    repo = MagicMock()
    repo.find_for_decision_role = AsyncMock(return_value=template)
    out = await template_selector.select_template("buyer", repo=repo)
    assert out is template
    repo.find_for_decision_role.assert_awaited_once_with("buyer")


@pytest.mark.asyncio
async def test_unit__template_selector__gatekeeper_returns_none() -> None:
    repo = MagicMock()
    repo.find_for_decision_role = AsyncMock(return_value=MagicMock())
    out = await template_selector.select_template("gatekeeper", repo=repo)
    assert out is None
    repo.find_for_decision_role.assert_not_called()


@pytest.mark.asyncio
async def test_unit__template_selector__unknown_falls_back_to_buyer() -> None:
    template = MagicMock()
    repo = MagicMock()
    repo.find_for_decision_role = AsyncMock(return_value=template)
    out = await template_selector.select_template("unknown", repo=repo)
    repo.find_for_decision_role.assert_awaited_once_with("buyer")
    assert out is template


@pytest.mark.asyncio
async def test_unit__template_selector__missing_template_returns_none() -> None:
    repo = MagicMock()
    repo.find_for_decision_role = AsyncMock(return_value=None)
    out = await template_selector.select_template("buyer", repo=repo)
    assert out is None


@pytest.mark.asyncio
async def test_unit__template_selector__case_insensitive() -> None:
    repo = MagicMock()
    repo.find_for_decision_role = AsyncMock(return_value=MagicMock())
    await template_selector.select_template("BUYER", repo=repo)
    repo.find_for_decision_role.assert_awaited_once_with("buyer")
