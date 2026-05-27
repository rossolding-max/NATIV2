# NATIV2 backend container — minimal multi-stage build.
# Production hardening (distroless, SBOM, scanning) lands in M17.

# ── Stage 1: builder ──────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /build

# Install deps first (better layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Copy app source + lock the project itself
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY README.md ./
RUN uv sync --frozen --no-dev

# ── Stage 2: runtime ──────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --no-create-home app

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/app /app/app
COPY --from=builder /build/alembic /app/alembic
COPY --from=builder /build/alembic.ini /app/alembic.ini

WORKDIR /app
USER app

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
