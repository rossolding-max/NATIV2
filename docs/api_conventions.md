# API Conventions

**Status:** Locked v0.1 (2026-05-26). Every FastAPI endpoint MUST follow these conventions. Tested via `tests/contract/` per `docs/test_plan.md` § 8.1.

---

## 1. URL structure

### 1.1 Versioning

Every endpoint lives under `/api/v1/`. No exceptions.

```
/api/v1/agencies                          # POST + GET (singleton in v0.1)
/api/v1/agencies/{agency_id}              # GET + PATCH
/api/v1/talents                           # POST + list
/api/v1/talents/{talent_id}               # GET + PATCH + DELETE (soft)
/api/v1/talents/{talent_id}/deals         # nested list
/api/v1/talents/{talent_id}/deals/{deal_id}/prep_packs
```

v2 ships its breaking changes under `/api/v2/`; `/api/v1/` continues to serve for the deprecation window (~6 months typical).

### 1.2 Resource pluralisation

- Collections: plural noun (`/talents`, `/deals`, `/brand_candidates`)
- Single resource: `{id}` segment under the plural (`/talents/{talent_id}`)
- Sub-collections: nested under parent (`/talents/{talent_id}/deals`)
- Actions on a resource that don't fit REST CRUD: verb suffix (`/deals/{deal_id}:advance`, `/proposal_packs/{id}:confirm_commercial`)

The colon-verb pattern for non-CRUD actions follows Google's [AIP-136](https://google.aip.dev/136). Keeps URLs noun-centric.

### 1.3 Webhook receivers

Separate prefix to clearly distinguish from agent-facing API:

```
/webhooks/smartlead/email_event
/webhooks/smartlead/reply
/webhooks/meta/oauth_callback
/webhooks/tiktok/oauth_callback
/webhooks/stripe/invoice_paid           # v2
```

Webhooks live OUTSIDE `/api/v1/` — they're not versioned in the same way + their auth model is signature-validation, not session.

### 1.4 Internal task polling

Long-running operations expose a status URL:

```
/api/v1/tasks/{task_id}                  # GET; returns task status + result when complete
```

---

## 2. Response envelope (always)

Every response — success OR error, single resource OR list — is wrapped:

```json
{
  "data": { ... },          // null on error
  "meta": {                  // always present
    "request_id": "req_01H...",
    "timestamp": "2026-05-27T14:30:00Z",
    "api_version": "v1"
  },
  "errors": []               // empty on success; populated on error
}
```

### 2.1 Single resource

```json
GET /api/v1/talents/riley-carter
HTTP 200 OK
Content-Type: application/json

{
  "data": {
    "id": "riley-carter",
    "agency_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Riley Carter",
    "..."
  },
  "meta": { "request_id": "req_01H...", "timestamp": "...", "api_version": "v1" },
  "errors": []
}
```

### 2.2 List

```json
GET /api/v1/talents?limit=50
HTTP 200 OK

{
  "data": [
    { "id": "riley-carter", "..." },
    { "id": "jane-doe", "..." }
  ],
  "meta": {
    "request_id": "req_01H...",
    "timestamp": "...",
    "api_version": "v1",
    "pagination": {
      "next_cursor": "eyJpZCI6Imp...",
      "has_more": true,
      "limit": 50
    }
  },
  "errors": []
}
```

### 2.3 Error

```json
POST /api/v1/talents
{ "name": "" }
HTTP 422 Unprocessable Entity

{
  "data": null,
  "meta": { "request_id": "req_01H...", "timestamp": "...", "api_version": "v1" },
  "errors": [
    {
      "code": "VALIDATION_ERROR",
      "field": "name",
      "message": "must not be empty",
      "detail": null
    }
  ]
}
```

### 2.4 Long-running operation accepted

```json
POST /api/v1/talents/riley/deals/d_002/prep_packs:generate
HTTP 202 Accepted

{
  "data": {
    "task_id": "task_01H...",
    "status_url": "/api/v1/tasks/task_01H...",
    "estimated_completion_seconds": 60
  },
  "meta": { "request_id": "req_01H...", "timestamp": "...", "api_version": "v1" },
  "errors": []
}
```

---

## 3. Error response shape

### 3.1 Error object structure

```typescript
{
  code: string,         // SCREAMING_SNAKE_CASE error code from the app's error taxonomy
  field?: string,       // optional JSONPath of the problematic field
  message: string,      // human-readable error message
  detail?: any,         // optional structured detail
}
```

### 3.2 Error code taxonomy

| HTTP status | Code prefix | Examples |
|---|---|---|
| 400 Bad Request | `BAD_REQUEST_*` | `BAD_REQUEST_MALFORMED_JSON` |
| 401 Unauthorized | `AUTH_REQUIRED_*` (v2) | `AUTH_REQUIRED_NO_SESSION` |
| 403 Forbidden | `FORBIDDEN_*` (v2) | `FORBIDDEN_WRONG_AGENCY`, `FORBIDDEN_INSUFFICIENT_ROLE` |
| 404 Not Found | `NOT_FOUND_*` | `NOT_FOUND_TALENT`, `NOT_FOUND_DEAL` |
| 409 Conflict | `CONFLICT_*` | `CONFLICT_OPTIMISTIC_LOCK`, `CONFLICT_IDEMPOTENCY_MISMATCH` |
| 422 Unprocessable Entity | `VALIDATION_*` | `VALIDATION_FIELD_REQUIRED`, `VALIDATION_INVALID_FORMAT`, `BUSINESS_RULE_VIOLATED` |
| 429 Too Many Requests | `RATE_LIMIT_*` | `RATE_LIMIT_VENDOR_QUOTA_EXCEEDED` |
| 500 Internal Server Error | `INTERNAL_*` | `INTERNAL_UNEXPECTED` |
| 502 Bad Gateway | `INTEGRATION_*` | `INTEGRATION_ANTHROPIC_DOWN`, `INTEGRATION_SMARTLEAD_TIMEOUT` |
| 503 Service Unavailable | `DEGRADED_*` | `DEGRADED_LLM_BUDGET_EXCEEDED` |

### 3.3 Validation errors (multiple fields)

Multiple validation failures stack in `errors[]`:

```json
HTTP 422

{
  "data": null,
  "meta": { ... },
  "errors": [
    { "code": "VALIDATION_FIELD_REQUIRED", "field": "name", "message": "required" },
    { "code": "VALIDATION_INVALID_FORMAT", "field": "platforms[0].handle", "message": "must start with @", "detail": { "got": "rileycarter" } }
  ]
}
```

---

## 4. Pagination

### 4.1 Cursor-based

```
GET /api/v1/deals?limit=20&cursor=eyJpZCI6Im...
```

Query params:
- `limit` — page size. Default 50. Max 200.
- `cursor` — opaque base64 of `{last_id, sort_field, sort_direction}`. Server constructs.

Response:
- `meta.pagination.next_cursor` — pass on next request to continue.
- `meta.pagination.has_more` — boolean; false on last page.
- `meta.pagination.limit` — echo of request.

### 4.2 No total_count by default

`total_count` is OPT-IN via `?include=total_count` because counting large tables is expensive. When requested:

```json
"meta": {
  "pagination": {
    "next_cursor": "...",
    "has_more": true,
    "limit": 50,
    "total_count": 12873
  }
}
```

### 4.3 Sorting + filtering

Sorting: `?sort=created_at:desc` (single field; comma-separate for multi). Whitelisted per endpoint.
Filtering: explicit query params per endpoint (e.g. `?stage=PROPOSAL&substage=proposal_sent`). NOT a generic `?filter=...` DSL (security + clarity).

---

## 5. Long-running operations

Pack generation, discovery runs, contract drafting can take 30s-3min. ALL such endpoints follow this pattern:

### 5.1 Kickoff

```
POST /api/v1/talents/{talent_id}/deals/{deal_id}/prep_packs:generate
HTTP 202 Accepted

{
  "data": {
    "task_id": "task_01H...",
    "status_url": "/api/v1/tasks/task_01H...",
    "estimated_completion_seconds": 60
  },
  "meta": { ... },
  "errors": []
}
```

### 5.2 Poll

```
GET /api/v1/tasks/{task_id}
HTTP 200 OK

# In progress
{
  "data": {
    "task_id": "task_01H...",
    "status": "running",
    "progress_pct": 45,
    "current_stage": "writer (slide generation)",
    "stages_completed": ["researcher", "extractor"],
    "started_at": "2026-05-27T14:30:00Z",
    "estimated_completion_seconds": 30
  },
  "meta": { ... },
  "errors": []
}

# Completed
{
  "data": {
    "task_id": "task_01H...",
    "status": "completed",
    "progress_pct": 100,
    "completed_at": "2026-05-27T14:31:23Z",
    "result_url": "/api/v1/talents/riley/deals/d_002/prep_packs/prep_..."
  },
  "meta": { ... },
  "errors": []
}

# Failed
{
  "data": {
    "task_id": "task_01H...",
    "status": "failed",
    "failed_at": "2026-05-27T14:30:45Z",
    "current_stage": "researcher",
    "failure_details": {
      "code": "INTEGRATION_EXA_TIMEOUT",
      "message": "Exa research timed out after 30s",
      "retryable": true
    }
  },
  "meta": { ... },
  "errors": []
}
```

### 5.3 Task status enum

- `queued` — accepted, not yet started
- `running` — in progress
- `completed` — success; `result_url` points to the created resource
- `failed` — `failure_details` populated; retry via `POST /api/v1/tasks/{task_id}:retry` if retryable
- `cancelled` — agent cancelled mid-run via `POST /api/v1/tasks/{task_id}:cancel`

### 5.4 Polling cadence

Frontend SHOULD poll every 2-5s. Server hints via `Retry-After` header on 202 + on each poll response. Long-idle tasks (no progress in 30s) bump suggested interval to 10s.

### 5.5 Tasks table

Tasks persist in Postgres:

```
task (
  task_id, agency_id, agent_id, kind, status, progress_pct, current_stage,
  result_url, failure_details, params, started_at, completed_at, expires_at
)
```

Retention: 30 days (configurable via `NATIV2_TASK_RETENTION_DAYS`). Cleanup cron prunes expired.

---

## 6. Idempotency

### 6.1 Header pattern (Stripe-style)

All non-idempotent endpoints (POST + DELETE; PATCH is naturally idempotent on full payload but supports the header) accept:

```
Idempotency-Key: client-generated-uuid-or-nanoid
```

The server stores `(idempotency_key, agency_id, response_status, response_body_hash, expires_at)` in Postgres. Repeated requests with the same key (within TTL) return the original response.

### 6.2 TTL

Default 24h. Configurable per endpoint via `IDEMPOTENCY_TTL_HOURS_<endpoint>`. Long-running operation kickoffs use 7d (so a frontend retry after a long task can still dedupe).

### 6.3 Mismatch detection

If the client sends the same key with a DIFFERENT body (e.g. they retried a `POST /talents` but changed the name), server returns `409 Conflict` with `CONFLICT_IDEMPOTENCY_MISMATCH`. Defends against accidental reuse of the same key for different operations.

### 6.4 Key recommendations

- Use UUIDv4 or nanoid; minimum 16 characters.
- Generate one key per logical user action (not per request).
- Send the key on every retry of that action.

### 6.5 Idempotent-by-design vs key-required

| Endpoint type | Idempotency-Key required | Reason |
|---|---|---|
| `GET *` | N/A | naturally idempotent |
| `PATCH *` | Optional | full-replace PATCH is idempotent; header adds replay-safety |
| `DELETE *` | Required | repeated DELETE of soft-deleted record is no-op; key prevents accidental duplicate audit entries |
| `POST */resource` | Required | creates a new record; without key, double-clicks create duplicates |
| `POST */:action` | Required | actions (advance deal, generate pack, send invoice) are not naturally idempotent |

---

## 7. Optimistic concurrency (If-Match)

### 7.1 Pattern

Pack regeneration + any update to versioned resources requires:

```
PATCH /api/v1/talents/riley/deals/d_002/proposal_packs/pp_..._v1
If-Match: "1"
Idempotency-Key: <uuid>

{ "commercial_proposal": { "confirmed_overrides": [...] } }
```

The server returns `409 Conflict CONFLICT_OPTIMISTIC_LOCK` if `If-Match` doesn't match the current `version`.

### 7.2 ETag exposure

Every response carries an `ETag` header:

```
HTTP 200 OK
ETag: "5"

{
  "data": {
    "version": 5,
    "..."
  },
  ...
}
```

Frontend reads the ETag from the response + sends it as `If-Match` on subsequent writes. OR reads `data.version` directly + sends as `If-Match` quoted.

### 7.3 Which resources are versioned

All pack types (`*_pack`): yes — concurrent regen risk.
`deal`: yes — multiple agents editing in v2 is plausible.
`talent`: yes — talent profile edits.
`agency_profile`: yes — invoice template changes are version-bumped per GAP-07 enforcement.
`brand_candidate` + `brand_contact` + `brand_deal`: not required v0.1 (low-contention); add ETag for v2-readiness.
`memo`: not required (memos are append-only; supersedes_memo_id chain is the version model).

---

## 8. Standard headers

### 8.1 Request headers

| Header | Required | Purpose |
|---|---|---|
| `Content-Type: application/json` | Required on POST/PATCH | Standard |
| `Idempotency-Key` | Per § 6.5 | Idempotency |
| `If-Match` | On writes to versioned resources | Optimistic concurrency |
| `X-Request-Id` | Optional (server generates if absent) | Distributed tracing |
| `X-Correlation-Id` | Optional | Long-running workflow tracing |
| `Accept: application/json` | Recommended | Future content negotiation |

### 8.2 Response headers

| Header | Always | Purpose |
|---|---|---|
| `X-Request-Id` | Always | Matches request or generated |
| `ETag` | On versioned resources | Optimistic concurrency |
| `Retry-After` | On 202 + 429 + 503 | Suggested retry interval (seconds) |
| `Content-Type: application/json; charset=utf-8` | Always | Standard |
| `X-LLM-Cost-USD` | On endpoints that consume LLM tokens (pack generation, classification) | Cost transparency to agent UI |

---

## 9. Status codes

| Code | When |
|---|---|
| 200 OK | Successful GET / PATCH / DELETE (soft) |
| 201 Created | Successful POST that created a resource. Response includes `Location` header. |
| 202 Accepted | Long-running operation kickoff. Response includes `task_id` + `status_url`. |
| 204 No Content | DELETE that completed without returning the resource (rare; we prefer 200 with the soft-deleted record returned). |
| 400 Bad Request | Malformed JSON; missing required header; unsupported media type |
| 401 Unauthorized | (v2) No session or invalid session |
| 403 Forbidden | (v2) Wrong agency or insufficient role |
| 404 Not Found | Resource doesn't exist for this agency |
| 409 Conflict | Optimistic-lock violation; idempotency-key mismatch; state-machine illegal transition |
| 422 Unprocessable Entity | Validation error; business rule violation |
| 429 Too Many Requests | (v2) Rate limit; (v0.1) vendor-quota exceeded passed through |
| 500 Internal Server Error | Unexpected; logged to Sentry |
| 502 Bad Gateway | Upstream vendor failure (Anthropic, Smartlead, Meta, etc.) |
| 503 Service Unavailable | Degraded mode (LLM budget exceeded; vendor disabled) |

Soft-deletes return 200 + the soft-deleted record (so the agent UI can show "Restored?" undo prompt). Hard deletes (v2 GDPR purge) return 204.

---

## 10. ID generation (server-side)

Every resource ID is server-generated. The server returns IDs in:

1. `201 Location` header on POST creates.
2. `data.id` (or per-resource id field) in the response body.

Client never POSTs with an ID field set; the server validates `id NOT IN payload` and rejects with 422 if present.

ID format per record type: see `docs/id_conventions.md`.

---

## 11. CORS (v2)

In v0.1, FastAPI and the stub frontend are served from the same origin (`http://127.0.0.1:8000`); CORS is not configured.

In v2, when the production frontend ships on a separate origin, configure:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,  # e.g. ["https://app.nativ.ai"]
    allow_credentials=True,  # for httpOnly cookie auth
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key", "If-Match", "X-Request-Id"],
    expose_headers=["ETag", "X-Request-Id", "X-LLM-Cost-USD", "Retry-After"],
    max_age=3600,
)
```

---

## 12. OpenAPI tags

Every endpoint is tagged for OpenAPI grouping:

| Tag | Endpoints |
|---|---|
| `Phase 0 — Agency Setup` | `/api/v1/agencies/*` |
| `Phase 1 — Talent Onboarding` | `/api/v1/talents` POST + `/api/v1/talents/{id}/onboarding/*` |
| `Phase 1.5 — Brand Deals` | `/api/v1/talents/{id}/brand_deals/*` |
| `Phase 2 — Brand Discovery` | `/api/v1/talents/{id}/brand_candidates/*` + `/api/v1/discovery_runs/*` |
| `Phase 3a — Contact CRM` | `/api/v1/brand_contacts/*` |
| `Phase 3b — Outreach` | `/api/v1/pitch_enrollments/*` + `/api/v1/pitch_templates/*` |
| `Phase 4 — Deal Lifecycle` | `/api/v1/deals/*` |
| `Phase 4.5 — Prep Pack` | `/api/v1/deals/{id}/prep_packs/*` |
| `Phase 4.6 — Proposal Pack` | `/api/v1/deals/{id}/proposal_packs/*` |
| `Phase 4.7 — Contract Pack` | `/api/v1/deals/{id}/contract_packs/*` |
| `Phase 4.8 — Invoice` | `/api/v1/deals/{id}/invoice_packs/*` + `/api/v1/deals/{id}/posting_detections/*` |
| `Phase 4.9 — Performance Report` | `/api/v1/deals/{id}/performance_report_packs/*` |
| `Memos` | `/api/v1/memos/*` |
| `Tasks` | `/api/v1/tasks/*` |
| `Uploads` | `/api/v1/uploads/*` |
| `Webhooks` | `/webhooks/*` (excluded from frontend OpenAPI by default; separate `/openapi_webhooks.json` for vendor docs) |

OpenAPI ships at `/openapi.json`; Swagger UI at `/docs`; ReDoc at `/redoc`.

---

## 13. Frontend OpenAPI workflow

Frontend devs consume the API spec via:

```bash
# Generate TypeScript types
npx openapi-typescript http://localhost:8000/openapi.json --output src/api/types.ts

# Generate a typed client (alternative)
npx openapi-fetch http://localhost:8000/openapi.json --output src/api/client.ts
```

Run on every backend release; commit the generated types to the frontend repo. CI gate: regenerate + diff — fail if drift.

---

## 14. Contract test enforcement (per `docs/test_plan.md` § 8.1)

CI requires:
1. Every route registered in `app.routes` has a corresponding contract test in `tests/contract/`.
2. Every endpoint exercises: success path + each documented error path + (v2) authz boundaries.
3. OpenAPI schema validates against the implementation via `schemathesis`.

Missing contract tests block PR merge.

---

## 15. Examples in the wild

### 15.1 Creating a talent

```http
POST /api/v1/talents
Idempotency-Key: idemp_01H1234...
Content-Type: application/json

{
  "name": "Riley Carter",
  "platforms": [
    {"platform": "instagram", "handle": "@rileycarter"},
    {"platform": "tiktok", "handle": "@rileycarter"}
  ],
  "content_niches": ["fitness", "wellness"],
  ...
}
```

```http
HTTP 201 Created
Location: /api/v1/talents/riley-carter
ETag: "1"

{
  "data": {
    "id": "riley-carter",
    "agency_id": "550e8400-...",
    "version": 1,
    "name": "Riley Carter",
    ...
  },
  "meta": { "request_id": "req_01H...", "timestamp": "2026-05-27T14:30:00Z", "api_version": "v1" },
  "errors": []
}
```

### 15.2 Generating a prep pack

```http
POST /api/v1/talents/riley-carter/deals/d_002/prep_packs:generate
Idempotency-Key: idemp_01H...
If-Match: "0"           # no existing prep pack yet
```

```http
HTTP 202 Accepted
Retry-After: 5

{
  "data": {
    "task_id": "task_01H...",
    "status_url": "/api/v1/tasks/task_01H...",
    "estimated_completion_seconds": 60
  },
  "meta": { ... },
  "errors": []
}
```

```http
GET /api/v1/tasks/task_01H...
```

(Poll every 2-5s until status: completed; then GET the result_url for the pack.)

### 15.3 Confirming commercial gate on a proposal

```http
POST /api/v1/talents/riley-carter/deals/d_002/proposal_packs/pp_..._v1:confirm_commercial
Idempotency-Key: idemp_01H...
If-Match: "1"

{
  "confirmed_overrides": [
    { "field": "fee_usd", "agent_value_decimal": "12500.00", "rationale": "Adjusted up from LLM proposal based on Lululemon 2024 comparable" }
  ]
}
```

```http
HTTP 200 OK
ETag: "2"

{
  "data": {
    "proposal_pack_id": "pp_...",
    "version": 2,
    "commercial_proposal": {
      "confirmed_at": "...",
      "confirmed_by_agent_id": "...",
      "confirmed_overrides": [...]
    },
    ...
  },
  "meta": { ... },
  "errors": []
}
```
