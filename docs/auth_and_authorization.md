# Authentication & Authorization

**Status:** Locked v0.1 (2026-05-26). Pairs with `docs/api_conventions.md` (envelope + headers) + `docs/architecture.md` § 7 (data layer multi-tenant readiness).

**v0.1 = no auth.** v2 SaaS introduces auth; the design is deferred until that pivot. This doc covers both.

---

## v0.1 — Single-tenant trusted environment

### Threat model

- App runs LOCALLY on the agency operator's machine via Docker Compose.
- One agency. One operator. No external network exposure expected.
- All API endpoints assume the caller is the trusted operator.
- All Celery workers, FastAPI processes, and Postgres run inside the same Docker network.

### Hard requirements

The app MUST be defensively configured to prevent accidental external exposure:

1. **Bind FastAPI to 127.0.0.1 by default.** `uvicorn ... --host 127.0.0.1`. To bind elsewhere, the operator must set `NATIV2_BIND_HOST=0.0.0.0` explicitly. Document the risk in `.env.example`.
2. **CORS:** disabled in v0.1 (no separate frontend origin; stub frontend served from the same FastAPI in dev). Document how to enable in `docs/api_conventions.md` when frontend ships.
3. **No CSRF:** N/A without auth. Document that v2 must add CSRF protection alongside session cookies.
4. **No rate limiting per-user:** N/A v0.1. Per-vendor rate limits (Anthropic / Meta Graph / etc.) still apply.

### agency_id propagation

Even without auth, `agency_id` propagates through the system for v2-readiness:

- On app startup, FastAPI initialises the singleton agency_id by reading the one `agency_profile` row from Postgres. If zero rows exist, the API exposes ONLY the `POST /api/v1/agencies` setup endpoint until Phase 0 completes. If multiple rows exist, the app refuses to start with a clear error ("v0.1 supports a single agency; found N. Run a migration or remove extras.").
- Singleton agency_id is held in `app.state.agency_id` (FastAPI lifespan).
- A FastAPI dependency `current_agency_id()` returns the singleton. All endpoints + Celery tasks consume via this dependency.
- All Postgres queries automatically filter by `agency_id = $current` via repository-layer enforcement (single source of truth). The `is_active` + `agency_id` scoping is applied in repositories, not in API handlers, so route code can't forget.

### agent_id propagation

- Singleton agent identity in v0.1: the first entry in `agency_profile.agents[]` (`maxItems: 1` constraint enforces single agent).
- A FastAPI dependency `current_agent_id()` returns this singleton.
- Endpoints that write `*_by_agent_id` fields (e.g. `confirmed_by_agent_id`, `sent_by_agent_id`) consume via this dependency.

### What v0.1 endpoints look like

```python
from app.api.deps import current_agency_id, current_agent_id

@router.post("/api/v1/talents")
async def create_talent(
    payload: TalentCreatePayload,
    agency_id: UUID = Depends(current_agency_id),
    agent_id: str = Depends(current_agent_id),
    repo: TalentRepository = Depends(),
) -> APIResponse[Talent]:
    talent = await repo.create(payload, agency_id=agency_id, created_by_agent_id=agent_id)
    return APIResponse(data=talent, meta=APIMeta(request_id=request_id_var.get()))
```

Note there's no `Depends(get_current_user)` or JWT validation. That's the v0.1 contract.

### Tests v0.1

- **Defensive bind:** integration test verifies FastAPI refuses to start with `NATIV2_BIND_HOST=0.0.0.0` unless `NATIV2_EXTERNAL_BIND_CONFIRMED=true` is also set. Belt + braces.
- **Multi-agency guard:** integration test seeds 2 agency_profile rows; app startup raises a clear error.
- **Agency singleton enforcement:** integration test verifies `current_agency_id()` returns the seeded singleton.
- **Repository scoping:** every repository method tested with 2 mocked tenants in DB; queries return only one tenant's rows. (Hardens v2 from day 1 even though v0.1 has one tenant.)

---

## v2 — Multi-tenant SaaS (deferred design)

When v2 SaaS ships, the following layers are added. **The specific auth provider decision is deferred.** Candidate options:

- **Clerk** — managed auth UI + JWT + 2FA + magic links. ~3 days integrate. ~$25/mo at small scale.
- **Supabase Auth** — open-source; can self-host or use cloud. ~5 days integrate. Free self-hosted.
- **Custom JWT** — bcrypt + httpOnly cookie + optional TOTP. ~2 weeks build.
- **Passwordless magic links** — Resend / Postmark. ~4-5 days build.

Decision lands in a separate ADR (architectural decision record) when the v2 work begins.

### Required v2 behaviours (provider-agnostic)

1. **Authentication:** every request must carry credentials. Stateless preferred (JWT in httpOnly cookie OR `Authorization: Bearer` header).
2. **agency_id propagation:** from the authenticated session, not the URL. Middleware extracts `agency_id` from the JWT claim + injects into request context. The repository layer's `agency_id` filter (already in place in v0.1) automatically scopes all queries.
3. **agent_id propagation:** same — from the JWT claim's `agent_id`.
4. **Cross-agency isolation:** enforced at THREE layers (defence in depth):
   - **Middleware:** rejects requests where the URL contains an `agency_id` that doesn't match the session's.
   - **Repository:** every read/write filters by `current_agency_id`. No exceptions.
   - **Postgres row-level security (RLS) policies:** as the final guarantor. Even raw SQL through the ORM gets filtered by RLS predicates on `agency_id`.
5. **Per-agent permissions (RBAC):** in v2, an agency may have multiple agents. Roles:
   - `owner` (full access, billing, agent management)
   - `operator` (full access on talents + deals + packs; no billing/agent management)
   - `viewer` (read-only)
   - `external_legal_reviewer` (only sees contract_pack.legal_review queue for their assigned talents)
   Defined in a `agency_agents.role` column. Endpoint decorators check role via `@requires(roles=["owner", "operator"])`.
6. **CSRF protection:** double-submit cookie pattern OR SameSite=Lax cookies + custom header check.
7. **Rate limiting per agency:** Redis-backed counters per `(agency_id, endpoint_group)`. Defaults: 100 reads/sec, 10 writes/sec, 5 pack-generations/min per agency.
8. **2FA:** TOTP via authenticator apps. Optional in v2.0; mandatory by v2.1.
9. **Session revocation:** logout endpoint invalidates the JWT (via a revoked-tokens table or short JWT TTL + refresh token).
10. **Audit log:** every authn / authz event logged with `(timestamp, agency_id, agent_id, event, resource_id, success)`. 90-day retention minimum.

### Migration from v0.1 → v2

The v0.1 singleton agency model + repository-layer `agency_id` filtering is the bridge. Migration steps:

1. Add auth provider (Clerk / Supabase / etc.).
2. Add `agency_agents` table with `role`.
3. Replace `current_agency_id()` and `current_agent_id()` FastAPI deps to read from the JWT claim instead of the singleton.
4. Migrate existing single-tenant data to a multi-tenant schema (every row already has `agency_id`; no data migration needed beyond agent identity).
5. Enable Postgres RLS policies.
6. Update OpenAPI spec to document auth requirements + 401 / 403 responses.
7. Update frontend to handle login flow.
8. Add audit log table + middleware.

No data migration churn. The repository layer remains the SAME interface — only its identity source changes from singleton to per-request JWT.

### Tests v2 (to author when v2 work starts)

- Every endpoint tested with: no token (401) / wrong agency token (403) / right agency wrong role (403) / right agency right role (200).
- Cross-agency boundary tests: agency A tokens cannot read agency B's data through ANY endpoint (incl. webhook receivers, file download presigned URLs, list endpoints).
- RLS policy tests: even with a SQL injection vulnerability or a buggy ORM query that forgets the filter, RLS blocks cross-tenant reads.
- Session revocation tests: logged-out session can't replay JWT until expiry.
- Rate-limit tests: 11th write/sec returns 429.
- 2FA flow tests (when enabled): login without TOTP code → 401; with code → 200.

---

## Webhook authentication (v0.1 + v2)

Webhook receivers (Smartlead, Meta Graph, TikTok, Stripe v2) use vendor-specific signature validation:

| Webhook | Mechanism | Header |
|---|---|---|
| Smartlead | HMAC-SHA256 with shared secret | `X-Smartlead-Signature` |
| Meta Graph | App secret HMAC-SHA256 over raw body | `X-Hub-Signature-256` |
| TikTok | HMAC-SHA256 with webhook secret | `X-Tiktok-Signature` |
| Stripe (v2) | Stripe webhook signing per docs | `Stripe-Signature` |

Each webhook receiver:
1. Reads the raw request body BEFORE Pydantic parsing.
2. Computes the expected signature using the per-vendor secret (stored in pgcrypto-encrypted column or env var).
3. Compares constant-time with the header.
4. Rejects with 401 + opaque error if mismatch.
5. Deduplicates via `(vendor, event_id)` idempotency table (configurable TTL per vendor; default 24h).
6. Logs the receipt event before processing (so even rejected webhooks have audit).

Tests:
- Valid signature → 200 + handler runs.
- Invalid signature → 401 + handler does NOT run.
- Replay of same event_id within TTL → 200 + handler does NOT run again.

---

## Summary

| Layer | v0.1 | v2 |
|---|---|---|
| End-user auth | None (single trusted operator) | JWT/cookie (provider TBD) |
| agency_id source | Singleton from DB | JWT claim |
| agent_id source | First agent in singleton | JWT claim |
| Repository scoping | `agency_id` filter (every method) | Same (filter source changes) |
| Cross-tenant defence | N/A (1 tenant) | Middleware + repository + RLS |
| Webhook auth | Per-vendor HMAC | Same |
| Rate limit | Per-vendor only | Per-agency + per-vendor |
| Audit log | Stage history + pack history per record | Above + dedicated authn/authz audit table |
| FastAPI bind | 127.0.0.1 (with explicit opt-in to bind elsewhere) | Whatever the deployment platform sets |
