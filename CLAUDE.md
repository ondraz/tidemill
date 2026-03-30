# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SaaS Subscription Analytics - A full-stack web application that computes and visualizes subscription business metrics (MRR, ARR, LTV, Retention, Churn, etc.) from Stripe data synced into a Clickhouse database.

**Stack**: FastAPI (Python) backend + React (Vite) frontend + Clickhouse database

## Development Commands

### Docker (Recommended for full stack)

```bash
# Start all services (frontend, backend, Clickhouse)
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Rebuild after changes
docker-compose up -d --build
```

Services when running via Docker:
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API docs: http://localhost:8000/docs
- Clickhouse HTTP: http://localhost:8123

### Backend Development

The backend is a modern Python project using `uv` for dependency management and a proper `src/` layout.

```bash
cd backend

# Quick setup
make install-dev

# Or use the setup script (installs uv if needed)
./dev-setup.sh

# Run development server
make run

# Run all checks (linting, type checking, tests)
make check

# Individual commands
make format      # Format code with black
make lint        # Run ruff linter
make typecheck   # Run mypy type checker
make test        # Run pytest tests
make clean       # Clean build artifacts

# See all available targets
make help
```

Manual commands (without Makefile):
```bash
# Install dependencies with uv
uv pip install -e ".[dev]"

# Run development server
uvicorn subscriptions.main:app --reload

# Code quality
black src/
ruff check src/
mypy src/
pytest
```

### Frontend Development

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview
```

### Database Operations

```bash
# Initialize database schema (when using standalone Clickhouse)
docker exec -i clickhouse clickhouse-client < init-db.sql

# Access Clickhouse CLI
docker exec -it subscriptions-clickhouse clickhouse-client

# Check Clickhouse connection
docker exec clickhouse clickhouse-client --query "SELECT 1"
```

### Stripe Data Sync

```bash
# Trigger manual Stripe data sync
curl -X POST http://localhost:8000/api/sync/stripe

# Or use the interactive API docs at http://localhost:8000/docs
```

## Architecture

### System Flow

```
Stripe API → FastAPI Backend → Clickhouse Database → React Frontend
                ↓
            Analytics Engine
         (Metrics Computation)
```

### Backend Architecture (`backend/`)

The backend is a **modern Python project** with proper packaging:

**Project Structure:**
```
backend/
├── pyproject.toml          # Project config, dependencies (uses uv)
├── .python-version         # Python version (3.11)
├── src/
│   └── subscriptions/      # Main package
│       ├── __init__.py
│       ├── main.py         # FastAPI app entry point
│       ├── models.py       # Pydantic models
│       ├── database.py     # Clickhouse client
│       ├── analytics.py    # Metrics computation
│       └── stripe_sync.py  # Stripe data sync
├── Dockerfile
└── README.md
```

The backend uses a **layered architecture**:

1. **subscriptions/main.py** - FastAPI application entry point
   - Defines REST API endpoints
   - Configures CORS for React frontend
   - Handles HTTP request/response lifecycle

2. **subscriptions/models.py** - Pydantic data models
   - `MetricType` enum: Defines available metrics (MRR, ARR, LTV, etc.)
   - `MetricData`: Time-series data structure (date + value)
   - Request/response validation

3. **subscriptions/database.py** - `ClickhouseClient` class
   - Abstracts Clickhouse database operations
   - Provides query methods: `get_customers()`, `get_subscriptions()`, `get_invoices()`
   - Currently uses mock implementation (returns empty arrays)
   - Production: Should implement actual clickhouse-driver queries

4. **subscriptions/analytics.py** - `AnalyticsEngine` class
   - **Core metrics computation logic**
   - Each metric has its own computation method (e.g., `compute_mrr()`, `compute_ltv()`)
   - Handles time-series aggregation by interval (day/week/month/year)
   - **Fallback behavior**: When no real data exists, generates sample data for demonstration
   - Period generation via `_generate_periods()` helper

5. **subscriptions/stripe_sync.py** - `StripeSync` class
   - Syncs data from Stripe API to Clickhouse
   - Methods: `sync_customers()`, `sync_subscriptions()`, `sync_invoices()`
   - Currently uses mock implementation
   - Production: Should implement actual Stripe SDK calls

### Database Schema (`init-db.sql`)

Three main tables in Clickhouse:

- **customers** - Customer records from Stripe
  - Engine: `ReplacingMergeTree(updated_at)` - handles upserts
  - Primary key: `id`

- **subscriptions** - Subscription data
  - Engine: `ReplacingMergeTree(updated_at)`
  - Primary key: `(id, customer_id)`
  - Tracks status, billing period, plan details
  - Indexes on `status` and `customer_id` for query performance

- **invoices** - Payment/invoice records
  - Engine: `ReplacingMergeTree(updated_at)`
  - Primary key: `(id, customer_id)`
  - Index on `customer_id`

### Frontend Architecture (`frontend/src/`)

Component structure:

- **App.jsx** - Root component
- **components/Dashboard.jsx** - Main dashboard layout
- **components/MetricsSummary.jsx** - Current metrics overview
- **components/MetricChart.jsx** - Individual metric time-series charts
- **services/api.js** - Axios-based API client for backend communication

### Metrics Computation Logic

All metrics are computed in `backend/analytics.py`:

- **MRR (Monthly Recurring Revenue)**: Sum of active subscription amounts, normalized to monthly
  - Annual plans divided by 12
  - Daily plans multiplied by 30

- **ARR (Annual Recurring Revenue)**: MRR × 12

- **Renewal Rate**: (Renewed subscriptions / Expiring subscriptions) × 100
  - Tracks subscriptions reaching period_end
  - Considers renewal if not canceled before period end

- **LTV (Lifetime Value)**: Average Revenue Per Customer / Churn Rate
  - Calculated per period from invoices and churn data

- **Retention Rate**: ((Customers at End - New Customers) / Customers at Start) × 100

- **Churn Rate**: (Churned Customers / Active Customers at Start) × 100
  - Based on subscription cancellations

- **Customer Count**: Total cumulative customers over time

## Environment Configuration

Copy `.env.example` to `.env` and configure:

- `STRIPE_API_KEY` - Stripe API key (required for data sync)
- `CLICKHOUSE_HOST` - Database host (default: localhost, or "clickhouse" in Docker)
- `CLICKHOUSE_PORT` - Database port (default: 9000)
- `VITE_API_URL` - Backend URL for frontend (default: http://localhost:8000)

## Important Implementation Notes

### Mock Data Behavior

The application currently uses **mock/sample data** for demonstration:

- `subscriptions/database.py` returns empty arrays from query methods
- `subscriptions/stripe_sync.py` doesn't actually call Stripe API
- `subscriptions/analytics.py` detects empty data and generates sample time series

When implementing real functionality:
1. Implement actual Clickhouse queries in `subscriptions/database.py` using `clickhouse-driver`
2. Implement Stripe API calls in `subscriptions/stripe_sync.py` using `stripe` SDK
3. Remove or update sample data generators in `subscriptions/analytics.py`

### Date Handling

- All dates stored in Clickhouse as `DateTime` type
- Python uses `datetime` objects
- API accepts dates in `YYYY-MM-DD` format
- Default query range: last 365 days

### CORS Configuration

Backend allows requests from:
- http://localhost:3000 (React dev server)
- http://localhost:5173 (Vite default port)

Update `main.py:24` when deploying to production domains.

## Common Workflows

### Adding a New Metric

1. Add enum value to `MetricType` in `src/subscriptions/models.py`
2. Implement `compute_<metric>()` method in `AnalyticsEngine` class (`src/subscriptions/analytics.py`)
3. Add case in `get_metric()` dispatcher method
4. Update frontend to display the new metric

### Modifying Database Schema

1. Update `init-db.sql`
2. Update corresponding query methods in `src/subscriptions/database.py`
3. Update Stripe sync methods in `src/subscriptions/stripe_sync.py` if needed
4. Rebuild Docker containers or re-run init script

### Testing API Changes

Use the interactive API documentation at http://localhost:8000/docs (Swagger UI provided by FastAPI).
