"""vcrpy configuration for LLM eval cassettes.

Cassettes live in ``tests/llm_eval/cassettes/`` (one per test function). The
default record mode is ``once`` — cassettes replay when present; fresh ones
record on first run. To re-record, pass ``--llm-record`` to pytest (sets mode
to ``new_episodes``).

Pre-record + pre-replay hooks scrub ``Authorization`` headers and the
``api_key`` field from request bodies. Cassettes are committed to git;
secrets must never leak in.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import vcr

CASSETTE_DIR = Path(__file__).resolve().parent / "cassettes"


def _scrub_request(request: Any) -> Any:
    """Strip Authorization header + api_key from request body."""
    if request.headers:
        # vcrpy gives header values as lists; replace in place.
        for key in list(request.headers.keys()):
            if key.lower() in {"authorization", "x-api-key", "anthropic-api-key"}:
                request.headers[key] = "[redacted]"
    return request


def _scrub_response(response: dict[str, Any]) -> dict[str, Any]:
    """Strip Authorization-like headers from response."""
    headers = response.get("headers", {})
    for key in list(headers.keys()):
        if key.lower() in {"authorization", "x-api-key", "anthropic-api-key"}:
            headers[key] = ["[redacted]"]
    return response


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--llm-record`` flag."""
    parser.addoption(
        "--llm-record",
        action="store_true",
        default=False,
        help="Re-record LLM cassettes against the live Anthropic API.",
    )


@pytest.fixture
def llm_cassette(request: pytest.FixtureRequest) -> Generator[Any, None, None]:
    """Per-test vcrpy cassette context.

    Usage:

        def test_my_agent(llm_cassette):
            # All anthropic API calls inside this context are recorded/replayed.
            ...

    Cassette path = ``tests/llm_eval/cassettes/<test_function_name>.yaml``.
    """
    from vcr.record_mode import RecordMode

    record_mode = (
        RecordMode.NEW_EPISODES if request.config.getoption("--llm-record") else RecordMode.ONCE
    )
    cassette_path = CASSETTE_DIR / f"{request.node.name}.yaml"
    CASSETTE_DIR.mkdir(parents=True, exist_ok=True)

    my_vcr = vcr.VCR(
        cassette_library_dir=str(CASSETTE_DIR),
        record_mode=record_mode,
        match_on=("method", "scheme", "host", "path"),
        before_record_request=_scrub_request,
        before_record_response=_scrub_response,
        filter_headers=["authorization", "x-api-key", "anthropic-api-key"],
    )
    with my_vcr.use_cassette(str(cassette_path)):
        yield
