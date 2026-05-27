# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x (current) | ✅ |
| < 0.1 | ❌ (pre-release) |

When v0.2 and later ship, security fixes apply to the latest minor + one prior. v0.1 will reach EOL when v0.2 ships.

---

## Reporting a vulnerability

**Do NOT open public GitHub issues for security vulnerabilities.**

Report privately to: `security@mercandco.com` (or via GitHub's "Report a security vulnerability" feature if enabled on the repo).

Include:

- A clear description of the vulnerability
- Steps to reproduce (proof-of-concept if available)
- Affected component(s) (FastAPI endpoint / Celery task / vendor wrapper / etc.)
- Severity assessment (your view)
- Suggested fix if known

We will:

1. Acknowledge receipt within 2 business days.
2. Assess + triage within 5 business days.
3. Develop a fix; coordinate disclosure timeline with you.
4. Credit you in the release notes (unless you prefer anonymity).

---

## Scope

In-scope for vulnerability reports:

- API endpoint vulnerabilities (auth bypass, injection, IDOR, etc.)
- Vendor webhook receiver vulnerabilities (signature bypass, replay)
- Cryptography weaknesses (pgcrypto config, secret storage)
- Cross-agency data leakage (v2 multi-tenant)
- PII handling violations (logging, error messages)
- Dependency vulnerabilities affecting the running app

Out-of-scope:

- Issues in test code / dev tooling / scripts not deployed
- Issues requiring a compromised dev machine (e.g. malicious `.env` content)
- Theoretical issues without proof-of-concept
- Social engineering / phishing tests
- Denial-of-service via expensive LLM calls (we have budget caps; not a vulnerability)

---

## Security practices

### Secrets

- Never committed. See `docs/configuration.md` § 5 for the list.
- Enforced via `trufflehog` in pre-commit + CI.
- Stored encrypted at rest (oAuth tokens via pgcrypto AES-256).
- Rotated on regular cadence in production (deferred to v2 for managed deploys).

### Authentication

- v0.1: no auth; relies on 127.0.0.1-only binding. See `docs/auth_and_authorization.md` for the trust model.
- v2: JWT/cookie auth with provider TBD; documented when v2 work begins.

### Authorization

- v0.1: trusted operator on local machine.
- v2: 3-layer defence (middleware + repository + Postgres RLS).

### Webhooks

- Signature validation per-vendor required BEFORE body parsing.
- Idempotency dedup table prevents replays.
- HMAC comparison is constant-time.

### Dependencies

- `uv` lock file (`uv.lock`) committed; reproducible builds.
- `safety` + `pip-audit` scan in CI.
- Critical vulnerabilities trigger nightly notifications.

### Data

- pgcrypto for sensitive columns (oAuth tokens, vendor API keys, signed contract clauses).
- Master key from env (`DB_MASTER_KEY`).
- TLS for all vendor API calls (httpx defaults).
- No PII in logs (enforced via structlog conventions + pre-commit checks).

### LLM prompt injection

- Untrusted external content (brand replies, brand brief uploads, contract redlines) flows through agents.
- Mitigations:
  - LLM outputs validated against JSON Schemas before consumption (prevents shape attacks)
  - Sensitive operations (state transitions, sends, payments) require agent confirmation gates — LLM cannot autonomously trigger them
  - Memos are factual + structured; prompt-injection-style content in a memo would still need to influence a downstream agent + pass a hard gate
- Reports of agent confusion / injection successfully bypassing a gate are HIGH priority.

---

## Vulnerability classification

We use CVSS 3.1. Severity targets for response time:

| Severity | Description | Acknowledgement | Fix target |
|---|---|---|---|
| Critical (9.0-10.0) | RCE, full DB compromise, cross-tenant breach | 24h | 72h |
| High (7.0-8.9) | Auth bypass, sensitive data exposure | 2 business days | 7 days |
| Medium (4.0-6.9) | XSS, CSRF, info disclosure (limited) | 5 business days | 30 days |
| Low (<4.0) | Hardening recommendations, minor info disclosure | 10 business days | 90 days |

## Past advisories

None at v0.1 launch. Updated as advisories accrete.
