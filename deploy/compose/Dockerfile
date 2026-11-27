# ── Stage 1: Build frontend ──────────────────────────────────────────────
FROM node:24-slim AS frontend-build

ARG VITE_CLERK_PUBLISHABLE_KEY

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --legacy-peer-deps
COPY frontend/ ./
RUN npx vite build

# ── Stage 2: Python application (API only — no frontend assets) ─────────
FROM python:3.14-slim AS api

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 tidemill && \
    useradd --uid 1000 --gid tidemill --create-home tidemill

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra observability

# Copy application code
COPY tidemill/ tidemill/
RUN uv sync --frozen --no-dev --no-editable --extra observability

# Drop to non-root user
RUN chown -R tidemill:tidemill /app
USER tidemill

# Default: API server (overridden per service in docker-compose.yml)
CMD ["uv", "run", "uvicorn", "tidemill.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Stage 3: Full build (API + frontend assets for Caddy) ───────────────
FROM api AS full

COPY --from=frontend-build --chown=tidemill:tidemill /app/frontend/dist /srv/frontend
