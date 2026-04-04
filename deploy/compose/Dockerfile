FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install dependencies first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra pg

# Copy application code
COPY subscriptions/ subscriptions/
RUN uv sync --frozen --no-dev --no-editable --extra pg

# Default: API server (overridden per service in docker-compose.yml)
CMD ["uv", "run", "uvicorn", "subscriptions.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
