# API & CLI

> FastAPI and CLI facades over the metrics engine.
> Last updated: April 2026

## Design

Both the HTTP API and CLI are thin facades. Every command/endpoint delegates to `MetricsEngine`. No business logic lives in the API or CLI layer.

## CLI (P0)

The CLI provides programmatic access to all metrics. It uses the same `MetricsEngine` as the HTTP API.

### Installation

```bash
pip install tidemill
# or
uv pip install tidemill
```

### Commands

```bash
# Current MRR
tidemill mrr
# $12,450.00

# MRR as of a specific date
tidemill mrr --at 2026-01-01

# MRR time series
tidemill mrr --start 2025-01-01 --end 2026-01-01 --interval month

# ARR
tidemill arr

# Net new MRR breakdown
tidemill mrr breakdown --start 2026-01-01 --end 2026-03-01

# Churn rate (default: logo churn)
tidemill churn --start 2026-01-01 --end 2026-03-01

# Revenue churn
tidemill churn --type revenue --start 2026-01-01 --end 2026-03-01

# Retention cohorts
tidemill retention --start 2025-01-01 --end 2026-01-01

# All metrics summary
tidemill summary

# Output as JSON (for piping to other tools)
tidemill mrr --format json

# Output as CSV
tidemill mrr --start 2025-01-01 --end 2026-01-01 --interval month --format csv
```

### Configuration

The CLI reads configuration from environment variables or a config file:

```bash
# Environment variables
export TIDEMILL_DATABASE_URL=postgresql://localhost/lago
export TIDEMILL_CONNECTOR=lago

# Or config file (~/.tidemill.toml or .tidemill.toml)
[database]
url = "postgresql://localhost/lago"

[connector]
type = "lago"
```

### Programmatic Usage (Python)

```python
import asyncio
from tidemill import MetricsEngine, QuerySpec

# Ingestion mode (Stripe) — engine queries materialized metric_* tables
engine = MetricsEngine(db=async_session)

# Same-database mode (Lago / Kill Bill) is configured per-metric by passing a
# DatabaseConnector into that metric's constructor or init(...) hook. The engine
# itself only owns the shared AsyncSession.

# Dynamic query dispatch — all metric queries are async
mrr = await engine.query("mrr", {"query_type": "current"})
churn = await engine.query("churn", {"start": date(2026, 1, 1), "end": date(2026, 2, 28), "type": "logo"})
cohorts = await engine.query("retention", {"query_type": "cohort_matrix",
                                            "start": date(2025, 1, 1), "end": date(2025, 12, 31)})

# With dimensions and filters via QuerySpec
spec = QuerySpec(
    dimensions=["customer_country"],
    filters={"currency": "USD"},
)
mrr_by_country = await engine.query("mrr", {"query_type": "current"}, spec=spec)

# Synchronous — no I/O
print(engine.available_metrics())
# ['churn', 'ltv', 'mrr', 'retention', 'trials']
```

## HTTP API

FastAPI is a thin HTTP layer. Every endpoint delegates to `engine.query()`. No business logic lives in the API layer.

```python
from fastapi import FastAPI, Depends, Query
from tidemill import MetricsEngine, QuerySpec
from tidemill.database import get_db

app = FastAPI(title="Tidemill API")

def get_engine() -> MetricsEngine:
    return MetricsEngine(get_db())

def parse_spec(
    dimensions: list[str] = Query(default=[]),
    filter: list[str] = Query(default=[]),    # "country=US", "plan_interval=monthly"
    granularity: str | None = None,
    segment: str | None = Query(default=None),         # universe filter (segment id)
    compare_segments: list[str] = Query(default=[]),    # per-branch slicing (segment ids)
) -> QuerySpec | None:
    filters = {}
    for f in filter:
        key, _, value = f.partition("=")
        filters[key] = value
    if not (dimensions or filters or granularity or segment or compare_segments):
        return None
    spec = QuerySpec(dimensions=dimensions, filters=filters, granularity=granularity)
    # Segment IDs are resolved to SegmentDef objects later, in `query_metric`,
    # so we don't need a DB session here.
    if segment:
        spec.filters["__segment_id__"] = segment
    if compare_segments:
        spec.filters["__compare_segment_ids__"] = list(compare_segments)
    return spec

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
| `GET` | `/api/metrics` | List of registered metric names |
| `GET` | `/api/metrics/summary` | MRR, ARR, churn, retention, LTV, ARPU, trial conversion in one call |
| `GET` | `/api/metrics/mrr` | MRR (point or series) |
| `GET` | `/api/metrics/arr` | ARR (point or series — same `start`/`end`/`interval` contract as MRR) |
| `GET` | `/api/metrics/mrr/breakdown` | Net new MRR breakdown by movement type |
| `GET` | `/api/metrics/mrr/waterfall` | Monthly MRR waterfall (movements per month) |
| `GET` | `/api/metrics/churn` | Churn rate (`type=logo` or `type=revenue`) |
| `GET` | `/api/metrics/churn/customers` | Per-customer churn detail (C_start / C_churned) |
| `GET` | `/api/metrics/churn/revenue-events` | Per-customer revenue-churn events |
| `GET` | `/api/metrics/retention` | Retention — `query_type=nrr` / `grr` / `cohort_matrix` |
| `GET` | `/api/metrics/ltv` | Simple LTV |
| `GET` | `/api/metrics/ltv/arpu` | ARPU (point) |
| `GET` | `/api/metrics/ltv/cohort` | Per-cohort LTV breakdown |
| `GET` | `/api/metrics/trials` | Trial conversion rate |
| `GET` | `/api/metrics/trials/funnel` | Trial funnel (started / converted / expired) |
| `GET` | `/api/metrics/trials/series` | Monthly trial time-series |
| `POST` | `/api/metrics/{metric}` | Generic query-by-body for any registered metric — body is `{"params": ..., "spec": {...}}` |

**Common query parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `at` | `date` | Point-in-time query (default: today) |
| `start` | `date` | Series start date |
| `end` | `date` | Series end date |
| `interval` | `string` | `day`, `week`, `month`, `year` |

**Segment parameters (apply to most metric endpoints):**

All metric endpoints share a common `QuerySpec` contract built from three query-string parameters (see `tidemill.metrics.route_helpers.parse_spec`):

| Parameter | Type | Description |
|-----------|------|-------------|
| `dimensions` | `string[]` | GROUP BY dimensions — names declared in the metric's Cube (e.g. `customer_country`, `currency`, `churn_type`, `cancel_reason`) |
| `filter` | `string[]` | Repeated `key=value` filters, e.g. `filter=customer_country=US&filter=currency=USD` |
| `granularity` | `string` | Time bucketing for series queries — `day`, `week`, `month`, `quarter`, or `year` |

Invalid dimension/filter names raise a `400` with the list of available options for that metric's cube. Dimensions that reach through the `plan` / `product` joins (`plan_interval`, `plan_name`, `product_name`, `pricing_model`, `collection_method`) are declared on the MRR cubes but will return no rows until the Stripe connector ingests `plan.*` / `product.*` events (see `docs/architecture/connectors.md`).

When `start` and `end` are provided, the endpoint returns a time series. Otherwise it returns a single value.

**Monetary values:** All monetary amounts are returned as **integer cents** (e.g., `$12.50` → `1250`). Divide by 100 in the client to display as dollars. This matches the internal storage convention (`*_cents` / `*_base_cents` columns) and avoids floating-point precision issues.

### Data

| Method | Path | Returns |
|--------|------|---------|
| `GET` | `/api/customers` | Paginated customer list |
| `GET` | `/api/customers/{id}` | Customer detail with subscriptions |
| `GET` | `/api/subscriptions` | Paginated subscription list |
| `GET` | `/api/invoices` | Paginated invoice list |

### Segments

Every metric endpoint (`/api/metrics/{mrr,churn,retention,ltv,trials}` and their
sub-paths) also accepts **`segment=<id>`** (universe filter) and
**`compare_segments=<id1>&compare_segments=<id2>…`** (per-branch slicing, up to
10). They compose — `segment` narrows the universe, `compare_segments` then
splits the narrowed rows by tagging each with every branch it matches. See
[segments.md](segments.md) for the compilation model.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/segments` | List all segments (workspace-shared) |
| `POST` | `/api/segments` | Create a segment (JSON `SegmentDef` body) |
| `GET`  | `/api/segments/{id}` | Fetch one |
| `PUT`  | `/api/segments/{id}` | Update name / description / definition |
| `DELETE` | `/api/segments/{id}` | Delete |
| `POST` | `/api/segments/validate` | Lint a definition without persisting |
| `GET`  | `/api/metrics/{name}/fields` | Discovery: dimensions + attributes + time_dimensions for the FE picker |

### Attributes

Customer attributes are keyed by `attribute_definition.key` and stored one-row-per-value in `customer_attribute`. Source may be `stripe` (fanned out from `customer.metadata`), `csv`, `api`, or `computed`.

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/attributes` | List attribute definitions |
| `POST` | `/api/attributes` | Create a definition (explicit type pinning) |
| `PUT`  | `/api/attributes/{key}` | Update label / description |
| `GET`  | `/api/attributes/{key}/values` | Distinct observed values (autocomplete) |
| `POST` | `/api/attributes/import` | Multipart CSV upload (first column is customer id) |
| `POST` | `/api/customers/{id}/attributes` | Upsert values on one customer |
| `DELETE` | `/api/customers/{id}/attributes/{key}` | Remove a value |

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

A runnable Bruno collection lives at [`bruno/`](../../bruno/) covering every
endpoint listed above — health, auth, sources, webhooks, metrics (with
working examples for `dimensions=`, `filter=`, `segment=`, and
`compare_segments=`), segments, attributes, dashboards, and saved charts.
Open the folder in the Bruno desktop app or run a request from the CLI:

```bash
bru run --env Local "Metrics - MRR/02_series.bru"
```

See `bruno/README.md` for the env vars and auth modes.
