# NATIV2 dev commands. See docs/dev_setup.md for the full developer guide.
#
# Quick-start:
#   just up           # boot local stack
#   just install      # install Python deps + pre-commit hooks
#   just migrate      # apply Alembic migrations
#   just dev-api      # run FastAPI dev server
#   just test         # run all tests

set shell := ["bash", "-cu"]
set dotenv-load := true

# ── Default ───────────────────────────────────────────────────────────
default:
    @just --list

# ── Stack lifecycle ───────────────────────────────────────────────────
up:
    docker compose up -d
    @echo "Stack starting. Run `just health` to verify."

down:
    docker compose down

down-volumes:
    docker compose down -v

restart:
    docker compose restart

# Reports per-service status (postgres, redis, minio, langfuse, mailpit).
health:
    @bash scripts/dev/health_check.sh

# ── Python + Python deps ──────────────────────────────────────────────
install:
    uv sync --all-extras
    uv run pre-commit install
    @echo "Done. Activate the venv with: source .venv/bin/activate"

# Refresh lock + install
sync:
    uv sync --all-extras

# Validate .env presence + required keys
validate-env:
    @bash scripts/dev/validate_env.sh

# ── Database ──────────────────────────────────────────────────────────
migrate:
    uv run alembic upgrade head

migrate-down:
    uv run alembic downgrade -1

db-status:
    uv run alembic current
    uv run alembic history --verbose | head -20

db-reset:
    docker compose down postgres -v
    docker compose up postgres -d
    @sleep 3
    just migrate

# ── Seeding ───────────────────────────────────────────────────────────
# Loads `data/brand_industry_map.json` (290 records) into the brand table.
# Idempotent — re-runs skip existing rows.
seed:
    uv run python scripts/import_brand_industry_map.py

seed-real:
    @echo "Seed: ~/.nativ/test_fixtures/ (lands in M4+ with full agency setup)."

# ── Dev servers ───────────────────────────────────────────────────────
dev-api:
    uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

dev-worker:
    uv run celery -A app.celery_app worker -Q default,llm_heavy -l info

dev-beat:
    uv run celery -A app.celery_app beat -l info

# Boot api + worker + beat together via process-compose
dev:
    process-compose up

# ── Tests ─────────────────────────────────────────────────────────────
test-unit:
    uv run pytest tests/unit/ -x -q

test:
    uv run pytest tests/unit tests/integration -x

test-full:
    uv run pytest tests/

test-llm-real:
    LIVE_LLM=1 uv run pytest tests/llm_eval/ -m live --budget=25

coverage:
    uv run pytest tests/unit tests/integration --cov=app --cov-report=html --cov-report=term
    @echo "Coverage report: htmlcov/index.html"

# ── Codegen ───────────────────────────────────────────────────────────
# Regenerate Pydantic models from JSON Schemas and record state for drift check.
# Flags locked per docs/spec_methodology.md + the M1 plan's "Implementation gotchas".
codegen:
    uv run datamodel-codegen \
        --input schemas \
        --input-file-type jsonschema \
        --output app/models/pydantic \
        --output-model-type pydantic_v2.BaseModel \
        --target-python-version 3.12 \
        --use-double-quotes \
        --field-constraints \
        --use-default \
        --reuse-model \
        --collapse-root-models \
        --use-schema-description \
        --capitalise-enum-members
    uv run python scripts/verify_pydantic_codegen.py --record

# ── Lint + typecheck ──────────────────────────────────────────────────
lint:
    uv run ruff check .
    uv run ruff format --check .

format:
    uv run ruff format .
    uv run ruff check --fix .

typecheck:
    uv run pyright

check: lint typecheck

# ── Pre-commit ────────────────────────────────────────────────────────
pre-commit-run:
    uv run pre-commit run --all-files

# ── Interactive phase walkthroughs (CLI lands in M2) ──────────────────
phase n:
    @echo "Phase walkthrough lands in M2 (per docs/test_plan.md § 4)."

# ── LLM cost report (lands later when Langfuse data exists) ───────────
llm-cost-report:
    @echo "LLM cost report lands in M2+ (per docs/test_plan.md § 5.4)."
