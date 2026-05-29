"""``exa_search`` + ``exa_get_contents`` agent tools.

Wraps the M3 ``ExaClient`` for use inside the Anthropic tool-use loop.
The researcher subagent calls these during Phase 4.5 discovery prep
generation to surface brand campaigns / news / contact background /
competitor landscape, with source URLs retained for the slides' citations
list.

Budget guardrails:
- ``MAX_QUERIES_PER_BIND`` caps total ``exa_search`` calls within a single
  ``bind_exa_tools`` invocation so a runaway researcher loop can't burn
  through the rate-limit budget. Per-pack max = 5 per the M11 plan.
- The base ``ExaClient`` already enforces vendor-side rate limits via
  ``check_rate_limit`` (60/min global).
"""

from __future__ import annotations

from typing import Any

from app.agents.base import ToolSpec
from app.utils.logging import get_logger
from app.vendors.exa import ExaClient

log = get_logger(__name__)

MAX_QUERIES_PER_BIND = 5

_EXA_SEARCH_SCHEMA: dict[str, Any] = {
    "description": (
        "Search the public web via Exa's neural + keyword index. Use for "
        "brand campaign discovery, contact background, competitor landscape, "
        "and recent news. Returns up to ``num_results`` hits with title + URL "
        "+ short snippet. Always keep the URLs — they land in the slide deck's "
        "sources list. Budget: up to 5 queries per pack generation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "minLength": 3, "maxLength": 256},
            "num_results": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            "include_domains": {"type": "array", "items": {"type": "string"}},
            "exclude_domains": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

_EXA_CONTENTS_SCHEMA: dict[str, Any] = {
    "description": (
        "Fetch parsed text content for one or more URLs returned by exa_search. "
        "Use sparingly — costs are higher than search. Call this only when a "
        "search snippet is too thin to ground a claim."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "maxItems": 5,
            }
        },
        "required": ["urls"],
        "additionalProperties": False,
    },
}


def bind_exa_tools(
    *,
    agent_name: str,
    client: ExaClient | None = None,
    max_queries: int = MAX_QUERIES_PER_BIND,
) -> dict[str, ToolSpec]:
    """Return runtime ToolSpecs bound to an ``ExaClient`` + per-bind budget.

    Pass a pre-built ``client`` to inject a mock during tests; production
    callers leave it unset so a fresh ``ExaClient`` is constructed (which
    requires ``settings.exa_api_key`` to be set).
    """
    state = {"queries_used": 0}

    def _build_client() -> ExaClient:
        return client if client is not None else ExaClient()

    async def _exa_search(
        query: str,
        num_results: int = 5,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ) -> dict[str, Any]:
        if state["queries_used"] >= max_queries:
            log.warning(
                "exa_search_budget_exhausted",
                agent_name=agent_name,
                max_queries=max_queries,
            )
            return {
                "budget_exhausted": True,
                "max_queries": max_queries,
                "results": [],
            }
        state["queries_used"] += 1
        exa = _build_client()
        raw = await exa.search(
            query,
            num_results=num_results,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )
        return {
            "query": query,
            "results": [
                {
                    "title": hit.get("title"),
                    "url": hit.get("url"),
                    "published_date": hit.get("publishedDate"),
                    "snippet": hit.get("text") or hit.get("summary"),
                    "score": hit.get("score"),
                }
                for hit in (raw.get("results") or [])
            ],
        }

    async def _exa_get_contents(urls: list[str]) -> dict[str, Any]:
        exa = _build_client()
        raw = await exa.get_contents(urls)
        return {
            "results": [
                {
                    "url": item.get("url"),
                    "title": item.get("title"),
                    "text": item.get("text"),
                }
                for item in (raw.get("results") or [])
            ],
        }

    return {
        "exa_search": ToolSpec("exa_search", _exa_search, _EXA_SEARCH_SCHEMA),
        "exa_get_contents": ToolSpec("exa_get_contents", _exa_get_contents, _EXA_CONTENTS_SCHEMA),
    }
