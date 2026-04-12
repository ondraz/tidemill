# ── Stage 1: Build frontend ──────────────────────────────────────────────
FROM node:22-slim AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python application (API only — no frontend assets) ─────────
FROM python:3.13-slim AS api

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY tidemill/ tidemill/
RUN uv sync --frozen --no-dev --no-editable

# Default: API server (overridden per service in docker-compose.yml)
CMD ["uv", "run", "uvicorn", "tidemill.api.app:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Stage 3: Full build (API + frontend assets for Caddy) ───────────────
FROM api AS full

COPY --from=frontend-build /app/frontend/dist /srv/frontend
