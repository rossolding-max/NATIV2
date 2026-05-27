# ID Conventions

**Status:** Locked v0.1 (2026-05-26). All IDs are **server-generated**. Client never POSTs with an ID; the server validates absence + creates the ID + returns it.

---

## 1. ID format per record type

| Record type | ID field | Format | Pattern | Example | Generation |
|---|---|---|---|---|---|
| `agency_profile` | `agency_id` | UUID v4 | `^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$` | `550e8400-e29b-41d4-a716-446655440000` | server `uuid.uuid4()` |
| `agency_profile.agents[]` | `agent_id` | kebab-slug | `^[a-z0-9][a-z0-9-]{1,63}$` | `ed-mercer` | server slugify(name) + collision suffix |
| `talent` | `id` | kebab-slug | `^[a-z0-9][a-z0-9-]{1,63}$` | `riley-carter` | server slugify(name) + collision suffix |
| `brand_industry_map.brands[]` | `brand_id` | kebab-slug | `^[a-z0-9][a-z0-9-]{1,63}$` | `lululemon-athletica` | server slugify(name) + collision suffix |
| `brand_candidate.candidates[]` | `candidate_id` | `bc_{nanoid}` | `^bc_[A-Za-z0-9_-]{12}$` | `bc_abc123xyz789` | server nanoid(12) |
| `brand_contact.contacts[]` | `contact_id` | `con_{nanoid}` | `^con_[A-Za-z0-9_-]{12}$` | `con_xyz789abc123` | server nanoid(12) |
| `brand_deal.deals[]` | `deal_id` | `bd_{YYYY}_{q}_{brand-slug}_{nanoid}` | `^bd_[0-9]{4}_q[1-4]_[a-z0-9-]+_[A-Za-z0-9_-]{8}$` | `bd_2024_q2_lululemon-athletica_abc12345` | server template |
| `pitch_template.templates[]` | `template_id` | kebab-slug | `^[a-z0-9][a-z0-9-]{1,63}$` | `buyer-direct-pitch-v1` | server slugify(name) + collision suffix |
| `pitch_angle.angles[]` | `angle_id` | `pa_{nanoid}` | `^pa_[A-Za-z0-9_-]{12}$` | `pa_abc123xyz789` | server nanoid(12) |
| `pitch_enrollment` | `enrollment_id` | `pe_{nanoid}` | `^pe_[A-Za-z0-9_-]{12}$` | `pe_abc123xyz789` | server nanoid(12) |
| `pitch_enrollment.steps[]` | `step_id` | sequential int | `^[1-9][0-9]*$` | `1`, `2`, `3` | server counter per enrollment |
| `pitch_enrollment.steps[].engagement_events[]` | `event_id` | `ee_{nanoid}` | `^ee_[A-Za-z0-9_-]{12}$` | `ee_abc123xyz789` | server nanoid(12) (or vendor-provided + prefixed) |
| `deal` (active) | `deal_id` | `deal_pipeline_{nanoid}` | `^deal_pipeline_[A-Za-z0-9_-]{12}$` | `deal_pipeline_abc123xyz789` | server nanoid(12) |
| `deal.lead.discovery_call_notes[]` | `note_id` | `note_{nanoid}` | `^note_[A-Za-z0-9_-]{12}$` | `note_abc123xyz789` | server nanoid(12) |
| `deal.proposal.negotiation_log[]` | `entry_id` | `neg_{nanoid}` | `^neg_[A-Za-z0-9_-]{12}$` | `neg_abc123xyz789` | server nanoid(12) |
| `deal.contract.amendment_log[]` | `entry_id` | `amd_{nanoid}` | `^amd_[A-Za-z0-9_-]{12}$` | `amd_abc123xyz789` | server nanoid(12) |
| `deal.delivery.posting_schedule[]` | `schedule_id` | `ps_{nanoid}` | `^ps_[A-Za-z0-9_-]{12}$` | `ps_abc123xyz789` | server nanoid(12) |
| `deal.delivery.interim_kpi_snapshots[]` | `snapshot_id` | `kpi_{nanoid}` | `^kpi_[A-Za-z0-9_-]{12}$` | `kpi_abc123xyz789` | server nanoid(12) |
| `deal.delivery.campaign_hashtags[]` | (inline string) | n/a — value IS the ID | n/a | `#rileyforlulu` | agent-entered |
| `deal.close.invoice_schedule[]` | `entry_id` | `is_{nanoid}` | `^is_[A-Za-z0-9_-]{12}$` | `is_abc123xyz789` | server nanoid(12) |
| `discovery_prep_pack` | `prep_pack_id` | `prep_{YYYYMMDD}_{nanoid}` | `^prep_[0-9]{8}_[A-Za-z0-9_-]{8}$` | `prep_20260527_abc12345` | server template |
| `discovery_prep_pack.slides[]` | `slide_id` | `slide_{nanoid}` | `^slide_[A-Za-z0-9_-]{12}$` | `slide_abc123xyz789` | server nanoid(12) |
| `proposal_pack` | `proposal_pack_id` | `pp_{YYYYMMDD}_{nanoid}` | `^pp_[0-9]{8}_[A-Za-z0-9_-]{8}$` | `pp_20260527_abc12345` | server template |
| `proposal_pack.slides[]` | `slide_id` | `slide_{nanoid}` (same as prep) | `^slide_[A-Za-z0-9_-]{12}$` | `slide_abc123xyz789` | server nanoid(12) |
| `proposal_pack.context_artefacts[]` | `artefact_id` | `art_{nanoid}` | `^art_[A-Za-z0-9_-]{12}$` | `art_abc123xyz789` | server nanoid(12) |
| `contract_pack` | `contract_pack_id` | `cp_{YYYYMMDD}_{nanoid}` | `^cp_[0-9]{8}_[A-Za-z0-9_-]{8}$` | `cp_20260527_abc12345` | server template |
| `contract_pack.context_artefacts[]` | `artefact_id` | `art_{nanoid}` | `^art_[A-Za-z0-9_-]{12}$` | `art_abc123xyz789` | server nanoid(12) |
| `invoice_pack` | `invoice_pack_id` | `inv_{YYYYMMDD}_seq{N}_v{M}_{nanoid}` | `^inv_[0-9]{8}_seq[0-9]+_v[0-9]+_[A-Za-z0-9_-]{6}$` | `inv_20260527_seq1_v1_abc123` | server template |
| `performance_report_pack` | `performance_report_pack_id` | `perf_{YYYYMMDD}_{nanoid}` | `^perf_[0-9]{8}_[A-Za-z0-9_-]{8}$` | `perf_20260527_abc12345` | server template |
| `memo` | `memo_id` | `memo_{nanoid}` | `^memo_[a-z0-9]+$` | `memo_abc123xyz789` | server nanoid(12, lowercase) |
| `task` (long-running ops) | `task_id` | `task_{nanoid}` | `^task_[A-Za-z0-9_-]{16}$` | `task_abc123xyz789def012` | server nanoid(16) |
| `upload` (presigned attachments) | `upload_id` | `up_{nanoid}` | `^up_[A-Za-z0-9_-]{12}$` | `up_abc123xyz789` | server nanoid(12) |
| `idempotency_key` (server-tracked) | `key` | client-supplied | `^[A-Za-z0-9_-]{16,64}$` | client-generated nanoid or UUID | client; server validates length |

---

## 2. nanoid configuration

```python
# app/utils/ids.py

from nanoid import generate

NANOID_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
# URL-safe; 64-char alphabet. ~71 bits of entropy at length 12.

def generate_nanoid(length: int = 12) -> str:
    return generate(NANOID_ALPHABET, size=length)
```

Memo IDs use a lowercase-only alphabet (legacy from initial schema):

```python
MEMO_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
```

---

## 3. Slug generation (kebab-case)

For talents, brands, agents, pitch templates:

```python
# app/utils/slugify.py

import re
import unicodedata

def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text[:64]  # max length cap
```

**Collision handling:** if `slugify(name)` already exists in scope (per § 4), append `-2`, `-3`, … until unique.

Example: two talents both named "Riley Carter" → `riley-carter`, `riley-carter-2`.

---

## 4. Uniqueness scope

| ID type | Uniqueness scope (v0.1) | Uniqueness scope (v2) |
|---|---|---|
| `agency_id` | Global | Global |
| `agent_id` | Within agency | Within agency |
| `talent.id` | Within agency | Within agency (`(agency_id, talent_id)` composite UNIQUE in DB) |
| `brand_id` | Global (shared catalog) | Global (shared catalog) |
| `candidate_id` | Within `brand_candidates` row (which is per-talent) | Same |
| `contact_id` | Within `brand_contact` row (which is per-brand, shared across agency talents) | Same |
| `deal_id` (active) | Global | Global |
| `deal_id` (archived; in `brand_deal.deals[]`) | Global | Global |
| `pack_id` (all pack types) | Global | Global |
| `memo_id` | Global | Global |
| `task_id` | Global | Global |
| `upload_id` | Global | Global |
| `step_id` (within enrollment) | Per-enrollment (sequential int starting 1) | Same |

DB constraints reflect this:
- Single-column PK on globally-unique IDs.
- Composite UNIQUE constraint on `(agency_id, talent.id)` etc. (the `agency_id` column is always present even though scoped IDs are globally unique in v0.1; this future-proofs for v2).

---

## 5. Why these formats (rationale)

### 5.1 UUID for `agency_id`

Random; non-guessable; safe in URLs. Standard for multi-tenant scope.

### 5.2 Kebab-slug for human-named entities

Talents, brands, agents, templates have human-readable names that operators want in URLs (`/talents/riley-carter`). UUIDs would be unfriendly. Kebab-slug is URL-safe + readable. Collision suffix handles dup names.

### 5.3 Prefixed nanoid for ephemeral / generated entities

`memo_abc123`, `pe_abc123`, `con_abc123`, etc. give a 2-3 character readability hint about what type the ID refers to (compare Stripe: `cus_*`, `ch_*`, `pi_*`). Also makes IDs scannable in logs.

71 bits of entropy at length 12 is sufficient for all reasonable scale (collision odds ~negligible at 10^9 records per type per agency).

### 5.4 Composite prefixed IDs for time-anchored records

`prep_20260527_abc12345` — packs include the generation date for visual scannability. Critical for debugging "which pack from when did this come from?"

`inv_20260527_seq1_v1_abc123` — invoice IDs include the sequence (which schedule entry) + version (regen count) + nanoid suffix. The full invoice number visible to the brand is computed separately via `agency_profile.invoice_template.invoice_number_sequence` (atomic counter; per the GAP-07 enforcement).

`bd_2024_q2_lululemon-athletica_abc12345` — archived brand_deals include year + quarter + brand for historical browsing.

---

## 6. ID validation discipline

Every Pydantic model with an ID field uses a Field-level pattern validator that matches the regex in § 1. Mismatched IDs → 422 on input + raise at DB load (defensive).

Example:

```python
from pydantic import BaseModel, Field

class Memo(BaseModel):
    memo_id: str = Field(..., pattern=r"^memo_[a-z0-9]+$")
    ...
```

The SQLAlchemy model uses a CHECK constraint on the column matching the same pattern:

```python
memo_id: Mapped[str] = mapped_column(
    String(64), primary_key=True,
    CheckConstraint(r"memo_id ~ '^memo_[a-z0-9]+$'"),
)
```

Defence in depth: Pydantic catches on API input; CHECK constraint catches on DB write through any path.

---

## 7. ID generation in code

```python
# app/utils/ids.py — single source of truth

from datetime import datetime, UTC
from uuid import uuid4
from app.utils.slugify import slugify
from app.utils.nanoid import generate_nanoid

def new_agency_id() -> UUID:
    return uuid4()

def new_talent_id(name: str, agency_id: UUID, existing_slugs: set[str]) -> str:
    base = slugify(name)
    if base not in existing_slugs:
        return base
    n = 2
    while f"{base}-{n}" in existing_slugs:
        n += 1
    return f"{base}-{n}"

def new_memo_id() -> str:
    return f"memo_{generate_nanoid(12, alphabet='abcdefghijklmnopqrstuvwxyz0123456789')}"

def new_pack_id(prefix: str) -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    suffix = generate_nanoid(8)
    return f"{prefix}_{today}_{suffix}"

def new_prep_pack_id() -> str: return new_pack_id("prep")
def new_proposal_pack_id() -> str: return new_pack_id("pp")
def new_contract_pack_id() -> str: return new_pack_id("cp")
def new_performance_report_pack_id() -> str: return new_pack_id("perf")

def new_invoice_pack_id(seq: int, version: int) -> str:
    today = datetime.now(UTC).strftime("%Y%m%d")
    suffix = generate_nanoid(6)
    return f"inv_{today}_seq{seq}_v{version}_{suffix}"

def new_task_id() -> str: return f"task_{generate_nanoid(16)}"
def new_upload_id() -> str: return f"up_{generate_nanoid(12)}"
def new_candidate_id() -> str: return f"bc_{generate_nanoid(12)}"
def new_contact_id() -> str: return f"con_{generate_nanoid(12)}"
def new_enrollment_id() -> str: return f"pe_{generate_nanoid(12)}"
def new_pitch_angle_id() -> str: return f"pa_{generate_nanoid(12)}"
def new_engagement_event_id() -> str: return f"ee_{generate_nanoid(12)}"
def new_slide_id() -> str: return f"slide_{generate_nanoid(12)}"
def new_artefact_id() -> str: return f"art_{generate_nanoid(12)}"
def new_note_id() -> str: return f"note_{generate_nanoid(12)}"
def new_negotiation_entry_id() -> str: return f"neg_{generate_nanoid(12)}"
def new_amendment_entry_id() -> str: return f"amd_{generate_nanoid(12)}"
def new_posting_schedule_id() -> str: return f"ps_{generate_nanoid(12)}"
def new_interim_kpi_snapshot_id() -> str: return f"kpi_{generate_nanoid(12)}"
def new_invoice_schedule_entry_id() -> str: return f"is_{generate_nanoid(12)}"

def new_deal_id_pipeline() -> str:
    return f"deal_pipeline_{generate_nanoid(12)}"

def new_deal_id_archived(year: int, quarter: int, brand_slug: str) -> str:
    suffix = generate_nanoid(8)
    return f"bd_{year}_q{quarter}_{brand_slug}_{suffix}"
```

This is the SINGLE entry point for ID creation. No other module generates IDs ad-hoc.

---

## 8. Tests

- `tests/unit/utils/test_ids.py` — every `new_*` function returns a value matching the regex from § 1.
- `tests/unit/utils/test_slugify.py` — covers Unicode normalisation + collision suffix + max-length cap.
- `tests/integration/test_id_collision_resistance.py` — generates 100k IDs of each type; asserts 0 collisions.
- `tests/contract/test_create_with_provided_id_rejected.py` — every POST endpoint rejects a request body containing an `id` field with 422.

---

## 9. Migration considerations

In v2, when `talent.id` becomes globally-non-unique (agency-scoped), existing v0.1 talents stay valid: they were globally unique in v0.1, which is a stronger constraint than agency-scoped uniqueness. No data migration needed.

The DB composite constraint `(agency_id, talent_id) UNIQUE` is added in v2 migration. The single-column constraint `talent_id UNIQUE` from v0.1 is removed.
