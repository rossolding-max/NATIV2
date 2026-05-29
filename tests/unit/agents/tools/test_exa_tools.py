"""``bind_exa_tools`` — schemas + budget cap + URL retention + content fetch."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agents.tools.exa_tools import MAX_QUERIES_PER_BIND, bind_exa_tools


def _fake_client(search_return: dict | None = None, contents_return: dict | None = None):
    client = AsyncMock()
    client.search = AsyncMock(return_value=search_return or {"results": []})
    client.get_contents = AsyncMock(return_value=contents_return or {"results": []})
    return client


def test_unit__exa_tools__schemas_have_required_shape() -> None:
    tools = bind_exa_tools(agent_name="researcher", client=_fake_client())
    assert set(tools) == {"exa_search", "exa_get_contents"}
    search_schema = tools["exa_search"].json_schema["input_schema"]
    assert search_schema["required"] == ["query"]
    assert search_schema["additionalProperties"] is False
    contents_schema = tools["exa_get_contents"].json_schema["input_schema"]
    assert contents_schema["required"] == ["urls"]


@pytest.mark.asyncio
async def test_unit__exa_tools__search_normalises_results_and_keeps_urls() -> None:
    raw = {
        "results": [
            {
                "title": "Alo Yoga campaign 2026",
                "url": "https://example.com/alo-2026",
                "publishedDate": "2026-03-15",
                "text": "Spring campaign featured 12 athletes ...",
                "score": 0.87,
            },
            {
                "title": "Alo Yoga Q1 2026 earnings",
                "url": "https://example.com/alo-earnings",
                "text": "Revenue up 22% YoY ...",
            },
        ]
    }
    client = _fake_client(search_return=raw)
    tools = bind_exa_tools(agent_name="researcher", client=client)
    out = await tools["exa_search"].callable_(query="Alo Yoga 2026 campaigns", num_results=5)
    assert out["query"] == "Alo Yoga 2026 campaigns"
    assert len(out["results"]) == 2
    # URLs must always be preserved — slides cite them.
    assert out["results"][0]["url"] == "https://example.com/alo-2026"
    assert out["results"][0]["title"] == "Alo Yoga campaign 2026"
    assert out["results"][0]["snippet"].startswith("Spring campaign")
    client.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_unit__exa_tools__search_enforces_budget_cap() -> None:
    raw = {"results": [{"title": "x", "url": "https://x", "text": "y"}]}
    client = _fake_client(search_return=raw)
    tools = bind_exa_tools(agent_name="researcher", client=client, max_queries=2)
    # 2 queries should pass through.
    a = await tools["exa_search"].callable_(query="q1")
    b = await tools["exa_search"].callable_(query="q2")
    assert "budget_exhausted" not in a
    assert "budget_exhausted" not in b
    assert client.search.await_count == 2
    # 3rd query hits the cap.
    c = await tools["exa_search"].callable_(query="q3")
    assert c["budget_exhausted"] is True
    assert c["max_queries"] == 2
    assert client.search.await_count == 2  # no extra vendor call


@pytest.mark.asyncio
async def test_unit__exa_tools__default_budget_matches_constant() -> None:
    """Default budget of 5 matches MAX_QUERIES_PER_BIND."""
    client = _fake_client(search_return={"results": []})
    tools = bind_exa_tools(agent_name="researcher", client=client)
    for i in range(MAX_QUERIES_PER_BIND):
        result = await tools["exa_search"].callable_(query=f"query_{i}")
        assert "budget_exhausted" not in result
    over = await tools["exa_search"].callable_(query="over")
    assert over["budget_exhausted"] is True


@pytest.mark.asyncio
async def test_unit__exa_tools__get_contents_returns_url_keyed_text() -> None:
    raw = {
        "results": [
            {
                "url": "https://example.com/a",
                "title": "Page A",
                "text": "Full body text of page A.",
            }
        ]
    }
    client = _fake_client(contents_return=raw)
    tools = bind_exa_tools(agent_name="researcher", client=client)
    out = await tools["exa_get_contents"].callable_(urls=["https://example.com/a"])
    assert len(out["results"]) == 1
    assert out["results"][0]["url"] == "https://example.com/a"
    assert out["results"][0]["text"] == "Full body text of page A."
    client.get_contents.assert_awaited_once_with(["https://example.com/a"])


@pytest.mark.asyncio
async def test_unit__exa_tools__search_forwards_domain_filters() -> None:
    client = _fake_client(search_return={"results": []})
    tools = bind_exa_tools(agent_name="researcher", client=client)
    await tools["exa_search"].callable_(
        query="alo yoga",
        include_domains=["aloyoga.com"],
        exclude_domains=["reddit.com"],
    )
    args = client.search.await_args
    assert args.kwargs["include_domains"] == ["aloyoga.com"]
    assert args.kwargs["exclude_domains"] == ["reddit.com"]
