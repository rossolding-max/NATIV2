"""Live smoke test for the Exa client. Env-gated."""

from __future__ import annotations

import os

import pytest

from app.vendors.exa import ExaClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not os.getenv("EXA_API_KEY"),
        reason="EXA_API_KEY not set; live test skipped.",
    ),
]


async def test_live__exa_search_returns_results() -> None:
    """A trivial search should return at least one result."""
    client = ExaClient()
    result = await client.search("Patagonia sustainability initiatives", num_results=3)
    assert "results" in result
