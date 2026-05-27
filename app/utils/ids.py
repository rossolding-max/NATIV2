"""ID generation helpers. Single source of truth — see ``docs/id_conventions.md``.

All ID generation in app code MUST go through this module (per ``CLAUDE.md``
"strict don'ts"). The per-record-type generators each guarantee:

- The output matches the regex documented in ``id_conventions.md`` § 1.
- Cryptographic random source (no `random.choice`).
- For human-readable IDs (talents, brands, agents): slugified base + collision
  suffix when the caller passes the set of existing slugs.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.utils.nanoid import MEMO_ALPHABET, generate_nanoid
from app.utils.slugify import slugify


def _today_yyyymmdd() -> str:
    """UTC date in YYYYMMDD format. Used as pack ID prefix."""
    return datetime.now(UTC).strftime("%Y%m%d")


# ── UUIDs (opaque identifiers) ───────────────────────────────────────


def new_agency_id() -> UUID:
    """Per-agency UUID. Multi-tenant readiness (v0.1 = single-tenant)."""
    return uuid4()


# ── Slug-based IDs (human-readable) ──────────────────────────────────


def new_agent_id(name: str, agency_id: UUID, existing: Iterable[str] | None = None) -> str:  # noqa: ARG001
    """Per-agent slug scoped to an agency.

    ``agency_id`` is part of the signature for v2 readiness — callers should
    pass it so v2's per-agency uniqueness audit can latch on.
    """
    return slugify(name, existing=existing)


def new_talent_id(name: str, agency_id: UUID, existing: Iterable[str] | None = None) -> str:  # noqa: ARG001
    """Per-talent slug scoped to an agency."""
    return slugify(name, existing=existing)


def new_brand_id(name: str, existing: Iterable[str] | None = None) -> str:
    """Brand slug (global to the system; brands are shared across talents)."""
    return slugify(name, existing=existing)


# ── Pack IDs (date-prefixed) ─────────────────────────────────────────


def new_pack_id(prefix: str) -> str:
    """Generic pack ID: ``{prefix}_{YYYYMMDD}_{8 chars}``.

    Used by every pack type. Prefix typically ``prep``, ``pp``, ``cp``,
    ``perf`` (see specific helpers below).
    """
    return f"{prefix}_{_today_yyyymmdd()}_{generate_nanoid(8)}"


def new_prep_pack_id() -> str:
    """Discovery prep pack (Phase 4.5). Format: ``prep_YYYYMMDD_{8}``."""
    return new_pack_id("prep")


def new_proposal_pack_id() -> str:
    """Commercial proposal pack (Phase 4.6). Format: ``pp_YYYYMMDD_{8}``."""
    return new_pack_id("pp")


def new_contract_pack_id() -> str:
    """Contract pack (Phase 4.7). Format: ``cp_YYYYMMDD_{8}``."""
    return new_pack_id("cp")


def new_performance_report_pack_id() -> str:
    """Performance report pack (Phase 4.9). Format: ``perf_YYYYMMDD_{8}``."""
    return new_pack_id("perf")


def new_invoice_pack_id(seq: int, version: int) -> str:
    """Invoice pack (Phase 4.8). Format: ``inv_YYYYMMDD_seq{N}_v{V}_{6}``.

    ``seq`` is the agency-scoped invoice sequence number; ``version``
    is incremented on each amended re-issue.
    """
    if seq < 0:
        raise ValueError("seq must be >= 0")
    if version < 1:
        raise ValueError("version must be >= 1")
    return f"inv_{_today_yyyymmdd()}_seq{seq}_v{version}_{generate_nanoid(6)}"


# ── Prefix-based opaque IDs ──────────────────────────────────────────


def new_memo_id() -> str:
    """Memo ID. Format: ``memo_{12 lowercase}``. Uses the 36-char alphabet."""
    return f"memo_{generate_nanoid(12, alphabet=MEMO_ALPHABET)}"


def new_task_id() -> str:
    """Long-running operation task ID. Format: ``task_{16}``."""
    return f"task_{generate_nanoid(16)}"


def new_upload_id() -> str:
    """File upload reference. Format: ``up_{12}``."""
    return f"up_{generate_nanoid(12)}"


def new_candidate_id() -> str:
    """Brand candidate ID (Phase 2). Format: ``bc_{12}``."""
    return f"bc_{generate_nanoid(12)}"


def new_contact_id() -> str:
    """Brand contact ID (Phase 3a). Format: ``con_{12}``."""
    return f"con_{generate_nanoid(12)}"


def new_enrollment_id() -> str:
    """Pitch enrollment ID (Phase 3b). Format: ``pe_{12}``."""
    return f"pe_{generate_nanoid(12)}"


def new_deal_id() -> str:
    """Active Phase 4 deal ID. Format: ``deal_{12}``."""
    return f"deal_{generate_nanoid(12)}"


def new_brand_deal_id() -> str:
    """Archived/historical brand_deal ID (Phase 1.5). Format: ``bd_{12}``."""
    return f"bd_{generate_nanoid(12)}"
