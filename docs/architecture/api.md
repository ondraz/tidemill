# API & CLI

> FastAPI and CLI facades over the metrics engine.
> Last updated: March 2026

## Design

Both the HTTP API and CLI are thin facades. Every command/endpoint delegates to `MetricsEngine`. No business logic lives in the API or CLI layer.

## CLI (P0)

The CLI provides programmatic access to all metrics. It uses the same `MetricsEngine` as the HTTP API.

### Installation

```bash
pip install subscriptions
# or
uv pip install subscriptions
```

### Commands

```bash
# Current MRR
subscriptions mrr
# $12,450.00

# MRR as of a specific date
subscriptions mrr --at 2026-01-01

# MRR time series
subscriptions mrr --start 2025-01-01 --end 2026-01-01 --interval month

# ARR
subscriptions arr

# Net new MRR breakdown
subscriptions mrr breakdown --start 2026-01-01 --end 2026-03-01

# Churn rate (default: logo churn)
subscriptions churn --start 2026-01-01 --end 2026-03-01

# Revenue churn
subscriptions churn --type revenue --start 2026-01-01 --end 2026-03-01

# Retention cohorts
subscriptions retention --start 2025-01-01 --end 2026-01-01

# All metrics summary
subscriptions summary

# Output as JSON (for piping to other tools)
subscriptions mrr --format json

# Output as CSV
subscriptions mrr --start 2025-01-01 --end 2026-01-01 --interval month --format csv
```

### Configuration

The CLI reads configuration from environment variables or a config file:

```bash
# Environment variables
export SUBSCRIPTIONS_DATABASE_URL=postgresql://localhost/lago
export SUBSCRIPTIONS_CONNECTOR=lago

# Or config file (~/.subscriptions.toml or .subscriptions.toml)
[database]
url = "postgresql://localhost/lago"

[connector]
type = "lago"
```

### Programmatic Usage (Python)

```python
import asyncio
from subscriptions import MetricsEngine, QuerySpec

# Ingestion mode (Stripe) — engine queries materialized metric_* tables
engine = MetricsEngine(db=async_session)

# Same-database mode (Lago) — engine also queries billing tables via connector
# from subscriptions.connectors import get_connector
# connector = get_connector("lago", engine=async_db_engine)
# engine = MetricsEngine(db=async_session, connector=connector)

# Dynamic query dispatch — all metric queries are async
mrr = await engine.query("mrr", {"query_type": "current"})
churn = await engine.query("churn", {"start": date(2026, 1, 1), "end": date(2026, 3, 1), "type": "logo"})
cohorts = await engine.query("retention", {"start": date(2025, 1, 1), "end": date(2026, 1, 1)})

# With dimensions and filters via QuerySpec
spec = QuerySpec(
    dimensions=["plan_interval"],
    filters={"plan_interval": {"in": ["yearly"]}, "customer_country": "US"},
)
enterprise_mrr = await engine.query("mrr", {"query_type": "current"}, spec=spec)

# Synchronous — no I/O
print(engine.available_metrics())
# ['churn', 'ltv', 'mrr', 'quick_ratio', 'retention', 'trials']
```

## HTTP API

FastAPI is a thin HTTP layer. Every endpoint delegates to `engine.query()`. No business logic lives in the API layer.

```python
from fastapi import FastAPI, Depends, Query
from subscriptions import MetricsEngine, QuerySpec
from subscriptions.database import get_db

app = FastAPI(title="Subscriptions API")

def get_engine() -> MetricsEngine:
    return MetricsEngine(get_db())

def parse_spec(
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),    # "country=US", "plan_interval=monthly"
    granularity: str | None = None,
) -> QuerySpec | None:
    filters = {}
    for f in filter:
        key, _, value = f.partition("=")
        filters[key] = value
    if not dimensions and not filters and not granularity:
        return None
    return QuerySpec(dimensions=dimensions, filters=filters, granularity=granularity)

@app.get("/api/metrics/mrr")
async def get_mrr(
    at: date | None = None,
    start: date | None = None,
    end: date | None = None,
    interval: str = "month",
    spec: QuerySpec | None = Depends(parse_spec),
    engine: MetricsEngine = Depends(get_engine),
):
    if start and end:
        return await engine.query("mrr", {"query_type": "series", "start": start,
                                          "end": end, "interval": interval}, spec=spec)
    return await engine.query("mrr", {"query_type": "current", "at": at}, spec=spec)
```

## Endpoints

### Metrics

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/api/metrics/mrr` | MRR (point or series) |
| `GET` | `/api/metrics/arr` | ARR (point or series) |
| `GET` | `/api/metrics/mrr/breakdown` | Net new MRR breakdown |
| `GET` | `/api/metrics/mrr/waterfall` | Monthly MRR waterfall (movements per month) |
| `GET` | `/api/metrics/churn` | Churn rate (logo or revenue) |
| `GET` | `/api/metrics/retention` | Cohort retention matrix |
| `GET` | `/api/metrics/ltv` | LTV (point or series) |
| `GET` | `/api/metrics/arpu` | ARPU (point or series) |
| `GET` | `/api/metrics/trials` | Trial conversion rate |
| `GET` | `/api/metrics/quick-ratio` | Quick ratio |
| `GET` | `/api/metrics/customers` | Customer count (point or series) |
| `GET` | `/api/metrics/summary` | All current metrics in one call |

**Common query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `at` | `date` | Point-in-time query (default: today) |
| `start` | `date` | Series start date |
| `end` | `date` | Series end date |
| `interval` | `string` | `day`, `week`, `month`, `year` |

**Segment parameters (apply to all metric endpoints):**

| Parameter | Type | Description |
|-----------|------|-------------|
| `source_ids` | `string[]` | Filter to specific billing sources |
| `customer_ids` | `string[]` | Filter to specific customers |
| `customer_tags` | `string[]` | Filter by customer tags |
| `customer_country` | `string[]` | ISO 3166-1 alpha-2 country codes |
| `plan_ids` | `string[]` | Filter to specific plans |
| `plan_intervals` | `string[]` | `monthly`, `yearly`, `quarterly`, etc. |
| `currencies` | `string[]` | ISO 4217 — shows original-currency amounts; omit for USD aggregate |
| `group_by` | `string[]` | Dimensional cut: `plan_id`, `plan_interval`, `customer_country`, `source_id`, `currency` |

When `start` and `end` are provided, the endpoint returns a time series. Otherwise it returns a single value.

### Data

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/api/customers` | Paginated customer list |
| `GET` | `/api/customers/{id}` | Customer detail with subscriptions |
| `GET` | `/api/subscriptions` | Paginated subscription list |
| `GET` | `/api/invoices` | Paginated invoice list |

### Connectors

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/sources` | List connected billing sources |
| `POST` | `/api/sources` | Add a billing source |
| `POST` | `/api/sources/{id}/backfill` | Trigger historical backfill |
| `POST` | `/api/webhooks/{source_id}` | Webhook receiver (translates and publishes to Kafka) |

### Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/healthz` | Liveness check |
| `GET` | `/readyz` | Readiness check (DB connected) |

## Authentication

Not included in v1. The API is designed to run behind a reverse proxy or VPN. Authentication can be added later via middleware.

## Interactive Documentation

FastAPI auto-generates OpenAPI docs at `/docs` (Swagger UI) and `/redoc`.
