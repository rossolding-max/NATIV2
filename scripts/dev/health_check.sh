#!/usr/bin/env bash
# Health check for the local NATIV2 dev stack.
# Returns 0 if all 5 services are ready, non-zero otherwise.

set -uo pipefail

ok() { printf "  \033[32m✓\033[0m %-12s %s\n" "$1" "$2"; }
err() { printf "  \033[31m✗\033[0m %-12s %s\n" "$1" "$2"; }

# Load .env if present (for ports/users)
if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

POSTGRES_PORT=${POSTGRES_PORT:-5432}
POSTGRES_USER=${POSTGRES_USER:-nativ2}
POSTGRES_DB=${POSTGRES_DB:-nativ2}
REDIS_PORT=${REDIS_PORT:-6379}
LANGFUSE_PORT=${LANGFUSE_PORT:-3000}

failed=0

# Postgres
if docker exec nativ2-postgres pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
    ok "Postgres:" "ready (127.0.0.1:$POSTGRES_PORT)"
else
    err "Postgres:" "not ready (127.0.0.1:$POSTGRES_PORT)"
    failed=$((failed + 1))
fi

# Redis
if docker exec nativ2-redis redis-cli ping 2>/dev/null | grep -q PONG; then
    ok "Redis:" "ready (127.0.0.1:$REDIS_PORT)"
else
    err "Redis:" "not ready (127.0.0.1:$REDIS_PORT)"
    failed=$((failed + 1))
fi

# MinIO
if curl -fsS http://127.0.0.1:9000/minio/health/ready >/dev/null 2>&1; then
    ok "MinIO:" "ready (http://127.0.0.1:9000  console: http://127.0.0.1:9001)"
else
    err "MinIO:" "not ready (http://127.0.0.1:9000)"
    failed=$((failed + 1))
fi

# Langfuse
if curl -fsS "http://127.0.0.1:$LANGFUSE_PORT/api/public/health" >/dev/null 2>&1; then
    ok "Langfuse:" "ready (http://127.0.0.1:$LANGFUSE_PORT)"
else
    err "Langfuse:" "not ready (http://127.0.0.1:$LANGFUSE_PORT)"
    failed=$((failed + 1))
fi

# Mailpit
if curl -fsS http://127.0.0.1:8025/readyz >/dev/null 2>&1; then
    ok "Mailpit:" "ready (http://127.0.0.1:8025)"
else
    err "Mailpit:" "not ready (http://127.0.0.1:8025)"
    failed=$((failed + 1))
fi

echo ""
if [[ $failed -eq 0 ]]; then
    echo "All 5 services healthy."
    exit 0
else
    echo "$failed service(s) not ready. Run \`just up\` or \`docker compose logs <svc>\` to diagnose."
    exit 1
fi
