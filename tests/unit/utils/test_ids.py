"""Hardening tests for ``app.utils.ids``.

Property-based collision tests + per-format regex validation.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.utils.ids import (
    new_agency_id,
    new_brand_deal_id,
    new_candidate_id,
    new_contact_id,
    new_contract_pack_id,
    new_deal_id,
    new_enrollment_id,
    new_invoice_pack_id,
    new_memo_id,
    new_pack_id,
    new_performance_report_pack_id,
    new_prep_pack_id,
    new_proposal_pack_id,
    new_task_id,
    new_upload_id,
)

_HEX36 = r"[a-z0-9]"
_URLSAFE64 = r"[A-Za-z0-9_-]"

# Format regexes per `docs/id_conventions.md` § 1.
_FORMATS: dict[str, tuple[Callable[[], str], str]] = {
    "new_memo_id": (new_memo_id, rf"^memo_{_HEX36}{{12}}$"),
    "new_task_id": (new_task_id, rf"^task_{_URLSAFE64}{{16}}$"),
    "new_upload_id": (new_upload_id, rf"^up_{_URLSAFE64}{{12}}$"),
    "new_candidate_id": (new_candidate_id, rf"^bc_{_URLSAFE64}{{12}}$"),
    "new_contact_id": (new_contact_id, rf"^con_{_URLSAFE64}{{12}}$"),
    "new_enrollment_id": (new_enrollment_id, rf"^pe_{_URLSAFE64}{{12}}$"),
    "new_deal_id": (new_deal_id, rf"^deal_{_URLSAFE64}{{12}}$"),
    "new_brand_deal_id": (new_brand_deal_id, rf"^bd_{_URLSAFE64}{{12}}$"),
    "new_prep_pack_id": (new_prep_pack_id, rf"^prep_[0-9]{{8}}_{_URLSAFE64}{{8}}$"),
    "new_proposal_pack_id": (new_proposal_pack_id, rf"^pp_[0-9]{{8}}_{_URLSAFE64}{{8}}$"),
    "new_contract_pack_id": (new_contract_pack_id, rf"^cp_[0-9]{{8}}_{_URLSAFE64}{{8}}$"),
    "new_performance_report_pack_id": (
        new_performance_report_pack_id,
        rf"^perf_[0-9]{{8}}_{_URLSAFE64}{{8}}$",
    ),
}


@pytest.mark.parametrize("name", list(_FORMATS.keys()))
def test_unit__id_format_matches_documented_regex(name: str) -> None:
    fn, pattern = _FORMATS[name]
    out = fn()
    assert re.match(pattern, out), f"{name} returned {out!r}; expected /{pattern}/"


@pytest.mark.parametrize("name", list(_FORMATS.keys()))
def test_unit__id_no_collisions_10k_draws(name: str) -> None:
    """Empirical collision sanity. 64-char alphabet at length 12 has ~71 bits
    of entropy; 10k draws should be collision-free.
    """
    fn, _ = _FORMATS[name]
    seen: set[str] = set()
    n = 10_000
    for _ in range(n):
        seen.add(fn())
    assert len(seen) == n, f"{name} collided {n - len(seen)} times in {n} draws"


def test_unit__agency_id_is_uuid() -> None:
    val = new_agency_id()
    assert isinstance(val, UUID)
    assert val.version == 4


def test_unit__pack_id_carries_todays_utc_date() -> None:
    today = datetime.now(UTC).strftime("%Y%m%d")
    out = new_pack_id("prep")
    assert out.startswith(f"prep_{today}_")


def test_unit__invoice_pack_id_structure() -> None:
    out = new_invoice_pack_id(seq=42, version=3)
    assert re.match(r"^inv_[0-9]{8}_seq42_v3_[A-Za-z0-9_-]{6}$", out)


def test_unit__invoice_pack_id_rejects_negative_seq() -> None:
    with pytest.raises(ValueError, match="seq"):
        new_invoice_pack_id(seq=-1, version=1)


def test_unit__invoice_pack_id_rejects_invalid_version() -> None:
    with pytest.raises(ValueError, match="version"):
        new_invoice_pack_id(seq=0, version=0)


def test_unit__memo_id_uses_lowercase_alphabet_only() -> None:
    """Memo IDs MUST use the 36-char alphabet (no upper / underscore / hyphen
    inside the suffix); enforce so future drift is caught.
    """
    for _ in range(500):
        out = new_memo_id()
        # Strip the 'memo_' prefix; remaining chars must all be a-z0-9.
        suffix = out.removeprefix("memo_")
        assert all(c.islower() or c.isdigit() for c in suffix), out


def test_unit__pack_ids_use_full_64_char_alphabet() -> None:
    """Across many draws, pack IDs should produce non-lowercase chars (proving
    they use the 64-char alphabet, not the memo 36-char alphabet).
    """
    saw_uppercase = False
    for _ in range(2000):
        suffix = new_task_id().removeprefix("task_")
        if any(c.isupper() for c in suffix):
            saw_uppercase = True
            break
    assert saw_uppercase, "task_id never produced uppercase in 2000 draws"
