# Developer Setup

**Status:** Locked v0.1 (2026-05-26). Read this first if you've just cloned the repo and want to run the stack.

**TL;DR:** Install Docker + uv + node 20 → copy `.env.example` to `.env` + add secrets → `make up` → `make migrate` → `make seed` → `make test`.

> **Note on current repo state:** The repo is currently in the SPEC phase. Code scaffolding lands at M0 (see `docs/project_plan.md`). This doc describes the target setup the dev team will create in M0. Files referenced below that don't yet exist will exist after M0 completes.

---

## 1. Prerequisites

| Tool | Required version | Why | Install |
|---|---|---|---|
| **Docker Desktop** | latest stable | Runs Postgres + Redis + MinIO + Langfuse locally | https://www.docker.com/products/docker-desktop |
| **uv** | latest | Python venv + dependency manager (~10x faster than pip) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Python 3.12** | exactly 3.12.x | Runtime | `uv python install 3.12` |
| **Node.js 20 LTS** | 20.x | Stub frontend (Vue 3 + Vite + Playwright) | https://nodejs.org/ or via nvm |
| **pnpm** | 9.x | Frontend dependency manager | `npm install -g pnpm` |
| **just** | latest | Command runner (replaces Makefile) | `cargo install just` or `brew install just` |
| **direnv** (optional but recommended) | latest | Auto-load `.env` per directory | `brew install direnv` (then add `eval "$(direnv hook bash)"` to shell rc) |

Verify:

```bash
docker --version          # 24+
uv --version              # 0.4+
python3.12 --version      # 3.12.x
node --version            # v20.x.x
pnpm --version            # 9.x.x
just --version            # 1.x
```

---

## 2. Clone + bootstrap

```bash
git clone git@github.com:rossolding-max/nativ2.git
cd nativ2

# Copy + fill in .env
cp .env.example .env
# Edit .env — set DB_MASTER_KEY (generate via `openssl rand -base64 32`)
#           set ANTHROPIC_API_KEY (sk-ant-...)
#           set POSTGRES_PASSWORD (any local value)
#           leave other vendor keys empty if you're not using them yet

# Optional: direnv auto-loads .env
direnv allow
```

Verify your `.env` is valid:

```bash
just validate-env
# Output: ✓ All required env vars present
```

---

## 3. Start the stack

```bash
just up
# Equivalent to: docker compose up -d
# Brings up: postgres, redis, minio, langfuse, mailhog (for local emails)
```

Verify services are healthy:

```bash
just health
# Output:
#   ✓ Postgres:   ready (127.0.0.1:5432)
#   ✓ Redis:      ready (127.0.0.1:6379)
#   ✓ MinIO:      ready (http://127.0.0.1:9000)  console: http://127.0.0.1:9001
#   ✓ Langfuse:   ready (http://127.0.0.1:3000)
#   ✓ Mailhog:    ready (http://127.0.0.1:8025)
```

---

## 4. Install Python deps

```bash
just install
# Equivalent to:
#   uv sync         # installs from uv.lock
#   uv run pre-commit install
```

Activate the venv (if your shell doesn't auto-activate):

```bash
source .venv/bin/activate
```

---

## 5. Migrate the database

```bash
just migrate
# Equivalent to: uv run alembic upgrade head
```

Verify:

```bash
just db-status
# Output: ✓ At revision <head_rev>; 23 tables present
```

---

## 6. Seed test data

```bash
just seed
# Loads the synthetic fixture: Acme Talent Agency + Riley Carter
# See docs/test_plan.md § 6 for what's in the synthetic fixture
```

For real-data local testing:

```bash
just seed-real
# Loads ~/.nativ/test_fixtures/ if present (real agency + real talent)
# See docs/test_plan.md § 7
```

---

## 7. Run the API + workers

In separate terminals (or via `just dev` which uses tmux or process-compose):

```bash
# Terminal 1 — FastAPI dev server (auto-reload)
just dev-api
# Equivalent to: uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2 — Celery worker (all queues)
just dev-worker
# Equivalent to:
#   uv run celery -A app.celery_app worker -Q default,llm_heavy,vendor_apis,rendering -l info

# Terminal 3 — Celery beat (cron scheduler)
just dev-beat
# Equivalent to: uv run celery -A app.celery_app beat -l info
```

Verify:

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok","version":"0.1.0","environment":"development"}

curl http://127.0.0.1:8000/openapi.json | jq '.info.title'
# "NATIV2 API"
```

Open the API docs:

```bash
open http://127.0.0.1:8000/docs    # Swagger UI
open http://127.0.0.1:8000/redoc   # ReDoc (cleaner)
```

---

## 8. Run tests

```bash
# Fast: unit tests only (~5s)
just test-unit

# Standard: unit + integration + contract (uses dockerised Postgres) (~3min)
just test

# Full: above + LLM eval (cassette) + e2e + frontend smoke (~10min)
just test-full

# Live LLM eval (real Anthropic calls — costs $) — gated
LIVE_LLM=1 just test-llm-real

# Verify coverage targets per docs/code_conventions.md
just coverage
# Opens htmlcov/index.html
```

---

## 9. Common dev workflows

### 9.1 Add a new API endpoint

1. Define request/response Pydantic models in `app/models/pydantic/...`.
2. Add the route in `app/api/{tag}.py` (see `docs/api_conventions.md` § 12 for the tag mapping).
3. Implement business logic in a service in `app/services/...`.
4. Add a repository method in `app/repositories/...` if it touches new DB queries.
5. Write tests: unit (service) + integration (with real DB) + contract (OpenAPI shape).
6. Re-generate frontend TS types if you'll touch the stub frontend:
   `cd tests/frontend_smoke && pnpm openapi-types`

### 9.2 Add a new database table

1. Define the JSON Schema in `schemas/{entity}.schema.json` if it's a new domain entity.
2. Update `app/models/pydantic/` (auto-generated from schema via `just codegen`).
3. Write the SQLAlchemy model in `app/models/sqla/foo.py`.
4. Generate an Alembic migration:
   `uv run alembic revision --autogenerate -m "add foo table"`
5. Inspect + edit the migration file in `alembic/versions/`.
6. Apply: `just migrate`
7. Add a factory in `tests/factories/foo.py`.
8. Add a repository class in `app/repositories/foo.py`.

### 9.3 Add a new Celery task

1. Define in `app/tasks/{queue}/task_name.py`.
2. Register in `app.celery_app` task imports.
3. If scheduled, add to `app/celery_app.py` Beat schedule.
4. Test as unit (mock vendor) + integration (real Celery worker).

### 9.4 Run a specific phase walkthrough

```bash
# Loads synthetic fixture + walks through Phase 0 interactively
just phase 0

# Or non-interactively
just phase 0 --auto

# Or against real fixture
just phase 0 --real
```

See `docs/test_plan.md` § 4 for the full `nativ test phase ...` CLI.

### 9.5 Re-generate Pydantic models from JSON Schemas

```bash
just codegen
# Equivalent to: uv run datamodel-code-generator --input schemas/ --output app/models/pydantic/
```

Pre-commit hook catches drift automatically; you'll be prompted to re-run if you edit a schema without regenerating.

### 9.6 Inspect LLM costs from the last session

```bash
just llm-cost-report
# Outputs reports/llm_cost_session.html
# Per-pack cost + per-agency aggregate from Langfuse data
```

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `docker compose up` fails: port conflict on 5432 | Local Postgres already running | Stop local Postgres OR change `POSTGRES_PORT` in `.env` + `docker-compose.yml` |
| `just migrate` fails: connection refused | Postgres not yet ready | `just health` to verify; wait 10s + retry |
| `just test` fails: ANTHROPIC_API_KEY missing | Real LLM enabled in test | Tests should use cassettes by default; check `tests/conftest.py` fixtures |
| `just dev-worker` exits immediately | Celery broker URL wrong | Verify `CELERY_BROKER_URL=redis://127.0.0.1:6379/0` in `.env` |
| Sentry / Langfuse traces missing | Either DSN unset or `LANGFUSE_ENABLED=false` | Set in `.env`; `LANGFUSE_ENABLED=true` for local |
| `just codegen` produces diff after schema edit | Pydantic models out of sync | Commit the regenerated files alongside the schema edit |
| Test fixture load hangs | DB has prior state | `just db-reset` then `just seed` |

---

## 11. IDE setup

### VS Code

Recommended extensions:

- `ms-python.python` (Python language support)
- `charliermarsh.ruff` (linting + formatting)
- `ms-python.vscode-pylance` (pyright LSP)
- `tamasfe.even-better-toml` (pyproject.toml syntax)
- `redhat.vscode-yaml` (compose + workflow syntax)
- `vue.volar` (Vue 3 for stub frontend)

`.vscode/settings.json` (committed):

```json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.analysis.typeCheckingMode": "strict",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": { "source.organizeImports.ruff": "explicit" }
  },
  "ruff.lint.run": "onType",
  "files.exclude": { "**/__pycache__": true, ".venv": true, "htmlcov": true }
}
```

### PyCharm

Set the interpreter to `.venv/bin/python`. Enable ruff via the Ruff plugin. Enable pyright via the integrated checker.

---

## 12. Repo layout (post-M0)

After M0 lands, the repo looks like this:

```
nativ2/
├── .editorconfig
├── .env.example
├── .github/
│   └── workflows/
│       ├── test.yml
│       ├── test-main.yml
│       ├── test-nightly.yml
│       └── test-release.yml
├── .gitignore
├── .pre-commit-config.yaml
├── .python-version
├── .vscode/
├── alembic/
│   ├── env.py
│   └── versions/
├── alembic.ini
├── app/                                 # all app code
│   ├── __init__.py
│   ├── main.py                          # FastAPI app + lifespan
│   ├── celery_app.py                    # Celery client + Beat schedule
│   ├── config.py                        # pydantic-settings
│   ├── errors.py                        # custom exception hierarchy
│   ├── api/                             # FastAPI routers
│   ├── agents/                          # Claude Agent SDK code
│   ├── cli/                             # `nativ` CLI (see test_plan.md § 4)
│   ├── db/
│   ├── models/
│   │   ├── pydantic/                    # auto-generated
│   │   └── sqla/                        # hand-written
│   ├── observability/
│   ├── repositories/
│   ├── services/
│   ├── tasks/
│   ├── utils/
│   │   ├── encryption.py                # pgcrypto wrappers
│   │   ├── ids.py                       # ID generation (see id_conventions.md § 7)
│   │   ├── slugify.py
│   │   ├── nanoid.py
│   │   ├── s3.py
│   │   └── logging.py
│   └── vendors/                         # external API wrappers
├── CLAUDE.md
├── CONTRIBUTING.md
├── data/                                # seed data
├── docker-compose.yml
├── docs/                                # all spec docs (this folder)
├── Dockerfile
├── justfile                             # all just commands
├── pyproject.toml
├── README.md
├── schemas/                             # JSON Schemas (source of truth)
│   └── _shared/
├── scripts/                             # standalone Python scripts
├── SECURITY.md
├── tests/
│   ├── conftest.py
│   ├── factories/
│   ├── fixtures/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── webhook_receivers/
│   ├── state_machine/
│   ├── llm_eval/
│   │   └── cassettes/
│   ├── e2e/
│   ├── frontend_smoke/                  # Vue 3 + Vite + Playwright
│   ├── performance/
│   ├── security/
│   ├── skip_handling/
│   └── live/
└── uv.lock
```

---

## 13. Where to read next

| You want to... | Read |
|---|---|
| Understand the system architecture | `docs/architecture.md` |
| Understand the build plan + milestone order | `docs/project_plan.md` |
| Understand any specific phase | `docs/{phase}_workflow.md` (e.g. `docs/onboarding_workflow.md`) |
| Understand cross-phase data flows | `docs/data_lineage.md` |
| Understand the test approach | `docs/test_plan.md` |
| Understand coding conventions | `docs/code_conventions.md` |
| Understand API conventions | `docs/api_conventions.md` |
| Understand auth model | `docs/auth_and_authorization.md` |
| Understand env vars + config | `docs/configuration.md` |
| Understand ID formats | `docs/id_conventions.md` |
| Submit a PR | `CONTRIBUTING.md` |
| Report a security issue | `SECURITY.md` |

---

## 14. Getting help

- **Spec questions:** open a GitHub issue tagged `question`.
- **Build questions:** ask in the team channel; reference the milestone (`M11` etc.).
- **Schema changes:** follow the discipline in `docs/code_conventions.md` § 14 + the schema migration discipline in `docs/project_plan.md` cross-cutting concerns.
