"""Search 16 — brands trending in the last 30 days (Reddit + X).

Wraps the existing ``~/.claude/skills/last30days/scripts/last30days.py``
skill via subprocess: for each top industry the talent has surfaced
through other searches, run a focused query (e.g. ``"<industry>
trending brands"``), parse the JSON output, scan item text for known
brand names from ``data/brand_industry_map.json``, and emit a
CandidateSource per matched brand.

Cost guard: capped fan-out (default top-3 industries). Disabled by
default in non-production environments via the
``enable_last30days_discovery`` settings flag — the skill needs real
OpenAI + xAI API keys to work.

Weight: 0.06 — modest signal. A brand showing up in the last 30 days
of social chatter inside the talent's industry is interesting but
needs to stack with other signals to clear the tertiary threshold.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from app.services.discovery._models import CandidateSource
from app.utils.logging import get_logger

log = get_logger(__name__)


_SEARCH_TAG: str = "last30days_trending"
_WEIGHT: float = 0.06
DEFAULT_MAX_INDUSTRIES: int = 3
DEFAULT_SUBPROCESS_TIMEOUT_S: float = 90.0

DEFAULT_SKILL_PATH: Path = (
    Path.home() / ".claude" / "skills" / "last30days" / "scripts" / "last30days.py"
)


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return cleaned or "unknown"


def _industry_label(industry_id: str) -> str:
    """Turn ``"supplements-brands"`` into ``"supplements brands"``."""
    return industry_id.replace("-", " ").replace("_", " ")


async def _invoke_skill(
    *, topic: str, skill_path: Path, mock: bool, timeout_s: float
) -> dict[str, Any] | None:
    """Run the skill as a subprocess, parse stdout JSON, return the Report dict."""
    if not skill_path.exists():
        log.warning("search_16_skill_missing", path=str(skill_path))
        return None
    cmd = ["python3", str(skill_path), topic, "--emit=json", "--quick"]
    if mock:
        cmd.append("--mock")
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except TimeoutError:
        log.warning("search_16_timeout", topic=topic)
        return None
    except Exception as exc:
        log.warning("search_16_subprocess_failed", topic=topic, error=str(exc))
        return None
    if proc.returncode != 0:
        log.warning(
            "search_16_skill_nonzero",
            topic=topic,
            code=proc.returncode,
            stderr=stderr_b.decode(errors="replace")[:500],
        )
        return None
    try:
        return json.loads(stdout_b.decode(errors="replace"))
    except json.JSONDecodeError:
        log.warning("search_16_json_parse_failed", topic=topic)
        return None


def _scan_text_for_brands(*, text: str, brand_lookup: dict[str, dict[str, Any]]) -> set[str]:
    """Return the lowercase brand-key matches found in ``text``."""
    if not text:
        return set()
    lowered = text.lower()
    matches: set[str] = set()
    for key in brand_lookup:
        # Full-word match: avoid "ag" hitting "stage" or "page".
        # \b boundary works for single-token brand names; multi-token names
        # use the literal key directly.
        if " " in key:
            if key in lowered:
                matches.add(key)
        else:
            if re.search(rf"\b{re.escape(key)}\b", lowered):
                matches.add(key)
    return matches


def _collect_text_blocks(report: dict[str, Any]) -> list[str]:
    """Pull title + comments + tweet text from the report into one list."""
    blocks: list[str] = []
    for item in report.get("reddit") or []:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if isinstance(title, str):
            blocks.append(title)
        why = item.get("why_relevant")
        if isinstance(why, str):
            blocks.append(why)
        for c in item.get("top_comments") or []:
            if isinstance(c, dict):
                body = c.get("body")
                if isinstance(body, str):
                    blocks.append(body)
        for insight in item.get("comment_insights") or []:
            if isinstance(insight, str):
                blocks.append(insight)
    for item in report.get("x") or []:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            blocks.append(text)
        why = item.get("why_relevant")
        if isinstance(why, str):
            blocks.append(why)
    return blocks


async def run(
    *,
    top_industry_ids: list[str],
    brand_industry_map: dict[str, Any],
    max_industries: int = DEFAULT_MAX_INDUSTRIES,
    skill_path: Path | None = None,
    mock: bool = False,
    timeout_s: float = DEFAULT_SUBPROCESS_TIMEOUT_S,
) -> list[CandidateSource]:
    """Run the last30days skill per top industry, mine for brand mentions."""
    if not top_industry_ids:
        return []

    industries = list(dict.fromkeys(top_industry_ids))[:max_industries]
    skill = skill_path or DEFAULT_SKILL_PATH

    # Build a name -> entry index for brand matching.
    brand_lookup: dict[str, dict[str, Any]] = {}
    for entry in brand_industry_map.get("brands") or []:
        if not isinstance(entry, dict):
            continue
        if not entry.get("industry_id"):
            continue
        name = entry.get("name")
        if isinstance(name, str) and name.strip():
            brand_lookup[name.strip().lower()] = entry
        for alias in entry.get("aliases") or []:
            if isinstance(alias, str) and alias.strip():
                brand_lookup[alias.strip().lower()] = entry

    if not brand_lookup:
        return []

    seen: set[str] = set()
    sources: list[CandidateSource] = []
    for industry_id in industries:
        topic = f"{_industry_label(industry_id)} trending brands"
        report = await _invoke_skill(topic=topic, skill_path=skill, mock=mock, timeout_s=timeout_s)
        if not report:
            continue
        text_blocks = _collect_text_blocks(report)
        if not text_blocks:
            continue
        haystack = "\n".join(text_blocks)
        matched_keys = _scan_text_for_brands(text=haystack, brand_lookup=brand_lookup)
        for key in matched_keys:
            entry = brand_lookup[key]
            brand_id = _slugify(entry["name"])
            if brand_id in seen:
                continue
            seen.add(brand_id)
            sources.append(
                CandidateSource(
                    brand_id=brand_id,
                    brand_name=entry["name"],
                    industry_id=entry["industry_id"],
                    search_tag=_SEARCH_TAG,
                    weight=_WEIGHT,
                    note=f"Mentioned in last-30-day trend pull for {industry_id!r}.",
                )
            )
    return sources
