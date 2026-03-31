# Metrics

> Each metric manages its own tables, registration, and computation.
> Last updated: March 2026

## Design

Each metric is self-contained. A metric:

1. **Declares its database tables** — the metric owns its schema, created on registration
2. **Registers itself** — declares a name, its query interface, and (optionally) the events it subscribes to
3. **Computes results** — either by querying billing tables directly (same-database mode) or by consuming events from Kafka (ingestion mode)
4. **Exposes queries** — the `MetricsEngine` delegates queries to the appropriate metric

This means adding a new metric requires zero changes to existing code. Write a metric class, register it, done.

### Dual-Mode Computation

Metrics support two computation modes, matching the [dual architecture](overview.md):

- **Event-driven mode** (ingestion) — the metric consumes events from Kafka and maintains its own materialized tables. This is the primary mode, used with Stripe and any webhook-based connector.
- **Direct-query mode** (same-database) — the metric queries billing tables via the `DatabaseConnector` at query time. Used with Lago/Kill Bill. No Kafka, no event processing. Lower priority.

Metrics must support at least one mode. The same metric can support both — using event-driven processing by default and falling back to direct queries when a `DatabaseConnector` is available.

### Metric Transparency

Every metric must document its computation methodology:

- **Formula** — the mathematical definition
- **SQL** — the actual query used to compute the metric
- **Assumptions** — what counts as "active", how partial months are handled, etc.
- **Edge cases** — how the metric behaves with zero customers, mid-month changes, etc.

This transparency is the project's core differentiator. Metric definitions are code: reviewable, forkable, contributable. No black boxes.

## Base Class

```python
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import MetaData


@dataclass
class SegmentFilter:
    """Declarative filter and dimensional cut for metric queries.

    **Filters** restrict which rows are included (WHERE clauses).
    **group_by** splits the result into one row per dimension value (GROUP BY).

    All filter fields are optional. Unset fields are not filtered on.
    Multiple values in a list are OR'd; across fields are AND'd.

    When group_by is set, query() returns a list of dicts:
        [{"plan_id": "plan_pro", "mrr_usd": 4200.00}, ...]
    When group_by is empty, query() returns a scalar or time series as usual.
    """
    # --- Filters (WHERE) ---

    # Billing source filter
    source_ids: list[str] = field(default_factory=list)

    # Customer attribute filters
    customer_ids: list[str] = field(default_factory=list)
    customer_tags: list[str] = field(default_factory=list)   # e.g. ["enterprise", "pilot"]
    customer_country: list[str] = field(default_factory=list)  # ISO 3166-1 alpha-2

    # Subscription attribute filters
    plan_ids: list[str] = field(default_factory=list)
    plan_intervals: list[str] = field(default_factory=list)  # "monthly" | "yearly" | ...
    subscription_statuses: list[str] = field(default_factory=list)

    # Currency filter (aggregates in USD when unset)
    currencies: list[str] = field(default_factory=list)  # ISO 4217; empty = all (USD aggregate)

    # --- Dimensional cut (GROUP BY) ---

    # Dimensions to group by. Supported values (metrics declare which they support):
    #   "plan_id"          — one row per plan
    #   "plan_interval"    — one row per billing interval (monthly/yearly/...)
    #   "customer_country" — one row per country
    #   "source_id"        — one row per billing source
    #   "currency"         — one row per currency (uses *_cents, not USD aggregate)
    #   "cohort_month"     — retention-specific: one row per cohort
    group_by: list[str] = field(default_factory=list)


class Metric(ABC):
    """Base class for metrics.

    All I/O methods are async — metrics use SQLAlchemy AsyncSession for database
    access and await connector calls. The engine and consumers are fully async.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Metric identifier, e.g. 'mrr', 'churn'."""
        ...

    @property
    def dependencies(self) -> list[str]:
        """Names of other metrics this metric depends on.
        The engine ensures all dependencies are registered and initialized
        before this metric is started.

        Example: QuickRatioMetric depends on MRR data, so it declares ['mrr'].
        The engine injects the MRR metric instance so this metric can query its tables.
        """
        return []

    @property
    def event_types(self) -> list[str]:
        """Event types this metric subscribes to (ingestion mode).
        Return empty list if metric only supports direct-query mode."""
        return []

    def register_tables(self, metadata: MetaData) -> None:
        """Define SQLAlchemy tables owned by this metric.
        Synchronous — called once at startup before the event loop runs."""
        pass

    async def handle_event(self, event: Event) -> None:
        """Process a single event (ingestion mode). Must be idempotent.
        Called by the async Kafka consumer for each matching event."""
        raise NotImplementedError("This metric does not support event-driven mode")

    @abstractmethod
    async def query(self, params: dict, segment: SegmentFilter | None = None) -> Any:
        """Answer a metric query.

        params: query-type-specific parameters (at, start, end, interval, ...)
        segment: optional filter to restrict results to a subset of data.
                 All built-in metrics support segmentation.

        Async — issues SQL via AsyncSession or awaits DatabaseConnector methods.
        """
        ...
```

## Registry

Metrics register themselves via a decorator:

```python
from subscriptions.metrics import register

@register
class MrrMetric(Metric):
    name = "mrr"
    dependencies = []   # no dependencies
    event_types = ["subscription.created", "subscription.activated",
                   "subscription.changed", "subscription.canceled",
                   "subscription.churned", "subscription.reactivated",
                   "subscription.paused", "subscription.resumed"]

    async def query(self, params, segment=None):
        if self.connector:  # same-database mode (Lago/Kill Bill)
            return await self._query_direct(params, segment)
        # Ingestion mode (Stripe) — primary path
        return await self._query_materialized(params, segment)


@register
class QuickRatioMetric(Metric):
    name = "quick_ratio"
    dependencies = ["mrr"]   # engine injects mrr metric at startup
    event_types = []         # no direct event subscription — reads mrr tables

    async def query(self, params, segment=None):
        # Queries metric_mrr_movement directly (injected via self.plugins["mrr"])
        ...
```

At startup, the engine:

1. Discovers all registered metrics
2. **Resolves dependency order** — topological sort of the dependency graph; raises on cycles
3. Initializes metrics in dependency order; injects resolved instances
4. Calls `register_tables()` on each — tables are added to the SQLAlchemy metadata
5. Runs Alembic migrations (or `metadata.create_all()` in dev)
6. **Ingestion mode only:** starts a Kafka consumer per metric (consumer group: `subscriptions.metric.{name}`)

## Lifecycle

### Ingestion Mode (Stripe) — Primary

```
Startup                     Runtime                        Query
   │                            │                             │
   │  register_tables()         │  Kafka event arrives        │  GET /api/metrics/mrr
   │  create tables if needed   │  ──────────────────►        │  ─────────────────►
   │  seek to last offset       │  handle_event(event)        │  metric.query(params)
   │                            │  update metric tables       │  → SQL against metric_* tables
   │                            │  commit offset              │  return result
```

### Replay / Backfill (Ingestion Mode Only)

When a new metric is added to an existing deployment:

1. Metric tables are created (empty)
2. Consumer group is new, so Kafka offset starts at the beginning (or reads from `event_log`)
3. All historical events are replayed through `handle_event()`
4. Metric catches up to head and starts processing live events

To recompute a metric from scratch: reset the consumer group offset to 0 and truncate the metric's tables.

### Same-Database Mode (Lago/Kill Bill) — Alternative

```
Startup                        Query
   │                             │
   │  register_tables()          │  GET /api/metrics/mrr
   │  create tables if needed    │  ─────────────────►
   │                             │  connector.get_mrr_cents()
   │                             │  → SQL against billing tables
   │                             │  return result
```

No Kafka, no event processing. The database connector queries billing tables at request time.

## Priority

| Metric | Priority | Scope |
|--------|----------|-------|
| MRR | **P0** | MRR, ARR, net new MRR breakdown |
| Churn | **P0** | Logo churn, revenue churn, net revenue churn |
| Retention | **P0** | Monthly cohorts, NRR, GRR |
| LTV | P1 | LTV, ARPU, cohort LTV |
| Trials | P1 | Trial conversion rate |

## Built-in Metrics

### MRR (P0)

**Subscribes to (ingestion mode):** `subscription.created`, `subscription.activated`, `subscription.changed`, `subscription.canceled`, `subscription.churned`, `subscription.reactivated`, `subscription.paused`, `subscription.resumed`

**Direct queries (same-database mode):** `DatabaseConnector.get_mrr_cents()`, `DatabaseConnector.get_subscription_changes()`

**Tables:**

```sql
-- Running MRR snapshot, updated on every subscription event
CREATE TABLE metric_mrr_snapshot (
    id              UUID PRIMARY KEY,
    source_id       UUID NOT NULL,
    customer_id     TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    mrr_cents       BIGINT NOT NULL,         -- current MRR in original currency
    mrr_usd_cents   BIGINT NOT NULL,         -- current MRR in USD (at rate on snapshot_at)
    currency        TEXT NOT NULL,           -- ISO 4217
    snapshot_at     TIMESTAMPTZ NOT NULL,    -- when this state took effect
    UNIQUE(source_id, subscription_id)
);

-- MRR movements (append-only log for breakdown queries)
CREATE TABLE metric_mrr_movement (
    id              UUID PRIMARY KEY,
    event_id        UUID NOT NULL UNIQUE,    -- idempotency: one movement per event
    source_id       UUID NOT NULL,
    customer_id     TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    movement_type   TEXT NOT NULL,           -- new | expansion | contraction | churn | reactivation
    amount_cents    BIGINT NOT NULL,         -- signed, original currency
    amount_usd_cents BIGINT NOT NULL,        -- signed, USD at rate on occurred_at
    currency        TEXT NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL
);
```

**Event handling:**

```python
async def handle_event(self, event: Event) -> None:
    match event.type:
        case "subscription.created" | "subscription.activated":
            await self._upsert_snapshot(event, event.payload["mrr_cents"],
                                        event.payload["mrr_usd_cents"])
            await self._append_movement(event, "new", event.payload["mrr_cents"],
                                        event.payload["mrr_usd_cents"])

        case "subscription.changed":
            prev, prev_usd = event.payload["prev_mrr_cents"], event.payload["prev_mrr_usd_cents"]
            new,  new_usd  = event.payload["new_mrr_cents"],  event.payload["new_mrr_usd_cents"]
            await self._upsert_snapshot(event, new, new_usd)
            delta, delta_usd = new - prev, new_usd - prev_usd
            kind = "expansion" if delta > 0 else "contraction"
            await self._append_movement(event, kind, delta, delta_usd)

        case "subscription.churned":
            prev, prev_usd = event.payload["prev_mrr_cents"], event.payload["prev_mrr_usd_cents"]
            await self._upsert_snapshot(event, 0, 0)
            await self._append_movement(event, "churn", -prev, -prev_usd)

        case "subscription.reactivated":
            mrr, mrr_usd = event.payload["mrr_cents"], event.payload["mrr_usd_cents"]
            await self._upsert_snapshot(event, mrr, mrr_usd)
            await self._append_movement(event, "reactivation", mrr, mrr_usd)

        case "subscription.paused":
            mrr, mrr_usd = event.payload["mrr_cents"], event.payload["mrr_usd_cents"]
            await self._upsert_snapshot(event, 0, 0)
            await self._append_movement(event, "churn", -mrr, -mrr_usd)

        case "subscription.resumed":
            mrr, mrr_usd = event.payload["mrr_cents"], event.payload["mrr_usd_cents"]
            await self._upsert_snapshot(event, mrr, mrr_usd)
            await self._append_movement(event, "reactivation", mrr, mrr_usd)
```

**Queries (dual-mode):**

```python
async def query(self, params: dict, segment=None) -> Any:
    match params.get("query_type"):
        case "current":
            if self.connector:
                # Same-database mode: query billing tables directly
                return await self.connector.get_mrr_usd_cents(params.get("at"))
            # Ingestion mode (primary): query materialized metric_mrr_snapshot
            return await self._current_mrr(params.get("at"), segment)
        case "series":
            return await self._mrr_series(params["start"], params["end"],
                                          params["interval"], segment)
        case "breakdown":
            return await self._mrr_breakdown(params["start"], params["end"], segment)
        case "arr":
            return await self.query({**params, "query_type": "current"}, segment) * 12
```

**Query building with `QueryBuilder`:**

`metric_mrr_snapshot` and `metric_mrr_movement` carry `source_id`, `customer_id`, `subscription_id`, and `currency`. `QueryBuilder` adds joins to `subscription`, `plan`, and `customer` lazily — only when a filter or `group_by` dimension actually needs them.

```python
async def _current_mrr(self, at: date | None, segment: SegmentFilter | None):
    # Use original-currency amounts when caller requested per-currency grouping
    amount_col = "mrr_cents" if (segment and "currency" in segment.group_by) else "mrr_usd_cents"

    qb = (
        QueryBuilder("metric_mrr_snapshot", alias="s")
        .select((func.sum(_col(f"s.{amount_col}")) / 100).label("mrr"))
        .where(_col("s.mrr_usd_cents") > 0)
    )
    if at:
        qb = qb.where(_col("s.snapshot_at") <= bindparam("at"), at=at)

    stmt, params = qb.apply_segment(segment).build()
    result = await self.db.execute(stmt, params)
    rows = result.mappings().all()
    # Scalar when no group_by, list of dicts when grouped
    if not (segment and segment.group_by):
        return rows[0]["mrr"] if rows else 0
    return [dict(r) for r in rows]
```

**Example: SQL generated by `QueryBuilder` for `_current_mrr` with various segments**

No segment — plain aggregate:
```sql
SELECT SUM(s.mrr_usd_cents) / 100.0 AS mrr
FROM metric_mrr_snapshot s
WHERE s.mrr_usd_cents > 0
```

`SegmentFilter(plan_intervals=["yearly"])` — filter only, no group_by:
```sql
SELECT SUM(s.mrr_usd_cents) / 100.0 AS mrr
FROM metric_mrr_snapshot s
JOIN subscription sub ON sub.source_id = s.source_id AND sub.external_id = s.subscription_id
JOIN plan p ON p.id = sub.plan_id
WHERE s.mrr_usd_cents > 0
  AND p.interval = ANY(:plan_intervals)
-- params: {"plan_intervals": ["yearly"]}
```

`SegmentFilter(group_by=["plan_interval", "customer_country"])` — dimensional cut:
```sql
SELECT SUM(s.mrr_usd_cents) / 100.0 AS mrr,
       p.interval AS plan_interval,
       c.country AS customer_country
FROM metric_mrr_snapshot s
JOIN subscription sub ON sub.source_id = s.source_id AND sub.external_id = s.subscription_id
JOIN plan p ON p.id = sub.plan_id
JOIN customer c ON c.source_id = s.source_id AND c.external_id = s.customer_id
WHERE s.mrr_usd_cents > 0
GROUP BY p.interval, c.country
```

`SegmentFilter(customer_country=["US", "DE"], group_by=["plan_id"])` — filter + cut combined:
```sql
SELECT SUM(s.mrr_usd_cents) / 100.0 AS mrr,
       sub.plan_id
FROM metric_mrr_snapshot s
JOIN subscription sub ON sub.source_id = s.source_id AND sub.external_id = s.subscription_id
JOIN customer c ON c.source_id = s.source_id AND c.external_id = s.customer_id
WHERE s.mrr_usd_cents > 0
  AND c.country = ANY(:customer_country)
GROUP BY sub.plan_id
-- params: {"customer_country": ["US", "DE"]}
```

**Breakdown query with `QueryBuilder`:**

```python
async def _mrr_breakdown(self, start: date, end: date, segment: SegmentFilter | None):
    stmt, params = (
        QueryBuilder("metric_mrr_movement", alias="m")
        .select(
            _col("m.movement_type").label("movement_type"),
            (func.sum(_col("m.amount_usd_cents")) / 100).label("amount_usd"),
        )
        .where(
            _col("m.occurred_at").between(bindparam("start"), bindparam("end")),
            start=start, end=end,
        )
        .group_by(_col("m.movement_type"))
        .apply_segment(segment)
        .build()
    )
    result = await self.db.execute(stmt, params)
    return [dict(r) for r in result.mappings().all()]
```

**Example: breakdown SQL generated by `QueryBuilder` with `SegmentFilter(group_by=["plan_id"])`:**
```sql
SELECT m.movement_type,
       SUM(m.amount_usd_cents) / 100.0 AS amount_usd,
       sub.plan_id
FROM metric_mrr_movement m
JOIN subscription sub ON sub.source_id = m.source_id AND sub.external_id = m.subscription_id
WHERE m.occurred_at BETWEEN :start AND :end
GROUP BY m.movement_type, sub.plan_id
```

### Churn (P0)

**Subscribes to (ingestion mode):** `subscription.churned`, `subscription.canceled`, `subscription.created`, `subscription.activated`, `subscription.reactivated`

**Metrics:** Logo churn rate, revenue churn rate, net revenue churn rate

**Tables:**

```sql
-- Tracks which customers are active at any point in time
CREATE TABLE metric_churn_customer_state (
    id                  UUID PRIMARY KEY,
    source_id           UUID NOT NULL,
    customer_id         TEXT NOT NULL,
    active_subscriptions INT NOT NULL DEFAULT 0,
    first_active_at     TIMESTAMPTZ,
    churned_at          TIMESTAMPTZ,
    UNIQUE(source_id, customer_id)
);

-- Churn events for rate calculation
CREATE TABLE metric_churn_event (
    id              UUID PRIMARY KEY,
    event_id        UUID NOT NULL UNIQUE,
    source_id       UUID NOT NULL,
    customer_id     TEXT NOT NULL,
    churn_type      TEXT NOT NULL,   -- logo | revenue
    mrr_cents       BIGINT,          -- revenue lost (for revenue churn)
    occurred_at     TIMESTAMPTZ NOT NULL
);
```

**Queries:**

Logo churn rate:

```sql
-- Customers who churned in period / customers active at period start
SELECT
    (SELECT COUNT(*) FROM metric_churn_event
     WHERE churn_type = 'logo'
       AND occurred_at BETWEEN :start AND :end)::float
    /
    NULLIF((SELECT COUNT(*) FROM metric_churn_customer_state
            WHERE first_active_at < :start
              AND (churned_at IS NULL OR churned_at >= :start)), 0)
    AS logo_churn_rate
```

Revenue churn rate (computed in USD for cross-currency correctness):

```sql
SELECT
    ABS(SUM(CASE WHEN m.movement_type = 'churn' THEN m.amount_usd_cents ELSE 0 END))::float
    /
    NULLIF((SELECT SUM(mrr_usd_cents) FROM metric_mrr_snapshot WHERE snapshot_at < :start), 0)
    AS revenue_churn_rate
FROM metric_mrr_movement m
WHERE m.occurred_at BETWEEN :start AND :end
```

### Retention (P0)

**Subscribes to (ingestion mode):** `subscription.created`, `subscription.activated`, `subscription.churned`, `subscription.reactivated`, `customer.created`

**Tables:**

```sql
-- Cohort membership (immutable once set)
CREATE TABLE metric_retention_cohort (
    id              UUID PRIMARY KEY,
    source_id       UUID NOT NULL,
    customer_id     TEXT NOT NULL,
    cohort_month    DATE NOT NULL,          -- month of first subscription
    UNIQUE(source_id, customer_id)
);

-- Monthly activity (one row per customer per active month)
CREATE TABLE metric_retention_activity (
    id              UUID PRIMARY KEY,
    source_id       UUID NOT NULL,
    customer_id     TEXT NOT NULL,
    active_month    DATE NOT NULL,
    UNIQUE(source_id, customer_id, active_month)
);
```

**Query — cohort retention matrix:**

```sql
SELECT
    c.cohort_month,
    a.active_month,
    COUNT(DISTINCT a.customer_id)::float
        / NULLIF(COUNT(DISTINCT c.customer_id), 0) AS retention_rate,
    EXTRACT(MONTH FROM age(a.active_month, c.cohort_month))::int AS months_since
FROM metric_retention_cohort c
LEFT JOIN metric_retention_activity a
    ON c.customer_id = a.customer_id AND c.source_id = a.source_id
WHERE c.cohort_month BETWEEN :start AND :end
GROUP BY c.cohort_month, a.active_month
ORDER BY c.cohort_month, a.active_month
```

**Net Revenue Retention (NRR) and Gross Revenue Retention (GRR):**

These query the MRR metric's movement table:

```
NRR = (start_mrr + expansion - contraction - churn) / start_mrr
GRR = (start_mrr - contraction - churn) / start_mrr
```

### LTV (P1)

**Subscribes to (ingestion mode):** `invoice.paid`, `subscription.churned`, `customer.created`

**Tables:**

```sql
-- Revenue per customer (updated on each paid invoice)
CREATE TABLE metric_ltv_customer_revenue (
    id               UUID PRIMARY KEY,
    source_id        UUID NOT NULL,
    customer_id      TEXT NOT NULL,
    total_cents      BIGINT NOT NULL DEFAULT 0,      -- original currency sum
    total_usd_cents  BIGINT NOT NULL DEFAULT 0,      -- USD equivalent sum
    currency         TEXT NOT NULL,                  -- ISO 4217
    invoice_count    INT NOT NULL DEFAULT 0,
    first_invoice_at TIMESTAMPTZ,
    last_invoice_at  TIMESTAMPTZ,
    UNIQUE(source_id, customer_id)
);
```

**Queries:**

Simple LTV: `ARPU / logo_churn_rate`

Cohort LTV: average `total_usd_cents` per customer grouped by cohort month (USD for cross-currency comparison); also available in original currency per `currency`.

ARPU: `SUM(mrr_usd_cents) / COUNT(DISTINCT active customers)` — queries MRR metric's snapshot table.

### Trials (P1)

**Subscribes to (ingestion mode):** `subscription.trial_started`, `subscription.trial_converted`, `subscription.trial_expired`

**Tables:**

```sql
CREATE TABLE metric_trial_event (
    id              UUID PRIMARY KEY,
    event_id        UUID NOT NULL UNIQUE,
    source_id       UUID NOT NULL,
    customer_id     TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    event_type      TEXT NOT NULL,       -- started | converted | expired
    occurred_at     TIMESTAMPTZ NOT NULL
);
```

**Query — conversion rate:**

```sql
SELECT
    COUNT(CASE WHEN event_type = 'converted' THEN 1 END)::float /
    NULLIF(COUNT(CASE WHEN event_type = 'started' THEN 1 END), 0)
    AS trial_conversion_rate
FROM metric_trial_event
WHERE occurred_at BETWEEN :start AND :end
```

## MetricsEngine

The engine dynamically discovers and delegates to metrics. It has no hardcoded metric methods — every metric is reached through the registry.

```python
class MetricsEngine:
    def __init__(
        self,
        db: AsyncSession,
        connector: DatabaseConnector | None = None,
        metrics: list[Metric] | None = None,
    ):
        self.db = db
        self.connector = connector
        # Auto-discover all @register metrics if none provided
        raw = metrics or discover_metrics()
        # Resolve dependency order (topological sort); raises on cycles or missing deps
        ordered = _resolve_dependencies(raw)
        # Initialize in order, injecting resolved instances
        # (synchronous — no I/O, just wiring)
        self._metrics: dict[str, Metric] = {}
        for m in ordered:
            deps = {name: self._metrics[name] for name in m.dependencies}
            m._init(db=db, connector=connector, deps=deps)
            self._metrics[m.name] = m

    async def query(
        self,
        metric: str,
        params: dict,
        segment: SegmentFilter | None = None,
    ) -> Any:
        """Route a query to the named metric. Works for any registered metric —
        built-in or custom — without engine changes."""
        if metric not in self._metrics:
            raise KeyError(f"No metric registered for '{metric}'. "
                           f"Available: {sorted(self._metrics)}")
        return await self._metrics[metric].query(params, segment=segment)

    def available_metrics(self) -> list[str]:
        """Return names of all registered metrics. Synchronous."""
        return sorted(self._metrics)
```

### Usage

```python
engine = MetricsEngine(db=async_session, connector=lago_connector)

# Any registered metric, any params — always awaited
await engine.query("mrr", {"query_type": "current"})
await engine.query("mrr", {"query_type": "series", "start": date(2025,1,1), "end": date(2026,1,1), "interval": "month"})
await engine.query("churn", {"start": date(2026,1,1), "end": date(2026,3,1), "type": "revenue"})
await engine.query("quick_ratio", {"start": date(2026,1,1), "end": date(2026,3,1)})

# With segmentation
segment = SegmentFilter(plan_ids=["plan_enterprise"], currencies=["EUR"])
await engine.query("mrr", {"query_type": "current"}, segment=segment)

# Synchronous — no I/O
engine.available_metrics()
# ['churn', 'ltv', 'mrr', 'quick_ratio', 'retention', 'trials']
```

The same `engine.query()` call is used from FastAPI, CLI, and Jupyter. The HTTP API maps URL path segments to metric names and query parameters to `params` + `segment`.

## Segmentation

`SegmentFilter` does two things:

1. **Filters** (WHERE) — restrict which rows are included
2. **Dimensional cuts** (GROUP BY via `group_by`) — split the result by a dimension

All built-in metrics support both.

### Filter Dimensions

| Field | SQL effect | Example |
|-------|-----------|---------|
| `source_ids` | `WHERE source_id = ANY(...)` | Multi-source deployments |
| `customer_ids` | `WHERE customer_id = ANY(...)` | Single-account drill-down |
| `customer_tags` | `JOIN customer_tag WHERE tag = ANY(...)` | `["enterprise", "pilot"]` |
| `customer_country` | `WHERE customer.country = ANY(...)` | `["US", "DE"]` |
| `plan_ids` | `WHERE plan_id = ANY(...)` | Per-plan filter |
| `plan_intervals` | `WHERE plan.interval = ANY(...)` | Monthly vs. annual |
| `subscription_statuses` | `WHERE status = ANY(...)` | Active-only, trialing, etc. |
| `currencies` | `WHERE currency = ANY(...)` | Per-currency amounts (uses `*_cents`) |

### Dimensional Cuts (`group_by`)

When `group_by` is set, the query groups results by those dimensions instead of returning a single aggregate. Metrics declare which `group_by` values they support.

| `group_by` value | SQL effect | Example result |
|-----------------|-----------|----------------|
| `"plan_id"` | `GROUP BY plan_id` | MRR per plan |
| `"plan_interval"` | `GROUP BY plan.interval` | MRR by monthly vs. annual |
| `"customer_country"` | `GROUP BY customer.country` | Churn rate by country |
| `"source_id"` | `GROUP BY source_id` | MRR per billing source |
| `"currency"` | `GROUP BY currency` | Revenue per currency (uses `*_cents`) |
| `"cohort_month"` | retention-specific | Cohort retention matrix |

Multiple dimensions can be combined: `group_by=["plan_interval", "customer_country"]` gives MRR for each interval × country combination.

**Return shape with `group_by`:**

```python
# engine.query("mrr", {"query_type": "current"}, segment=SegmentFilter(group_by=["plan_id"]))
[
    {"plan_id": "plan_starter",      "mrr_usd": 2900.00},
    {"plan_id": "plan_professional", "mrr_usd": 6320.00},
    {"plan_id": "plan_enterprise",   "mrr_usd": 3230.00},
]

# group_by=["plan_interval", "customer_country"]
[
    {"plan_interval": "monthly", "customer_country": "US",  "mrr_usd": 4100.00},
    {"plan_interval": "monthly", "customer_country": "DE",  "mrr_usd":  980.00},
    {"plan_interval": "yearly",  "customer_country": "US",  "mrr_usd": 5200.00},
    ...
]
```

**Return shape without `group_by`:** scalar or time-series as usual.

### QueryBuilder

All metrics build their SQL through a shared `QueryBuilder` (`subscriptions/metrics/query.py`). It accumulates a SQLAlchemy `Select` statement via proper statement-manipulation methods (`.add_columns()`, `.where()`, `.join()`, `.group_by()`) — no string concatenation. JOINs are added lazily only when a filter or group_by dimension requires them, and resolved in dependency order.

```python
# subscriptions/metrics/query.py

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable, ClassVar

from sqlalchemy import Select, and_, bindparam, func, literal_column, select, table
from sqlalchemy.sql.elements import ClauseElement


@dataclass
class _JoinDef:
    # Returns (join_target, on_clause) as SQLAlchemy expressions.
    # `a` is the base table alias (e.g. "s").
    join_fn: Callable[[str], tuple[Any, ClauseElement]]
    depends_on: list[str]


@dataclass
class _DimDef:
    # Returns labelled column expression for SELECT.
    select_fn: Callable[[str], ClauseElement]
    # Returns column expression for GROUP BY.
    group_by_fn: Callable[[str], ClauseElement]
    requires_joins: list[str]


@dataclass
class _FilterDef:
    # Returns a WHERE ClauseElement. `a` = base alias, `pk` = bind param name.
    condition_fn: Callable[[str, str], ClauseElement]
    param_key: str
    requires_joins: list[str]
    get_value: Callable[[SegmentFilter], list]


def _col(expr: str) -> ClauseElement:
    """Shorthand: literal SQL column/expression reference."""
    return literal_column(expr)


class QueryBuilder:
    """
    Fluent metric SQL builder backed by a SQLAlchemy Select statement.

    The builder accumulates column expressions, WHERE conditions, JOINs, and
    GROUP BY clauses using SQLAlchemy's Select API. apply_segment() drives the
    SegmentFilter → statement transformation. build() returns the finished
    Select and the bind-params dict; callers pass both to db.execute().

    Usage:
        stmt, params = (
            QueryBuilder("metric_mrr_snapshot", alias="s")
            .select(func.sum(_col("s.mrr_usd_cents")) / 100)
            .where(_col("s.mrr_usd_cents") > 0)
            .apply_segment(segment)
            .build()
        )
        rows = await db.execute(stmt, params)
    """

    # ------------------------------------------------------------------ #
    # Class-level registries                                              #
    # ------------------------------------------------------------------ #

    _JOINS: ClassVar[dict[str, _JoinDef]] = {
        "subscription": _JoinDef(
            join_fn=lambda a: (
                table("subscription").alias("sub"),
                and_(
                    _col("sub.source_id")   == _col(f"{a}.source_id"),
                    _col("sub.external_id") == _col(f"{a}.subscription_id"),
                ),
            ),
            depends_on=[],
        ),
        "plan": _JoinDef(
            join_fn=lambda a: (
                table("plan").alias("p"),
                _col("p.id") == _col("sub.plan_id"),
            ),
            depends_on=["subscription"],
        ),
        "customer": _JoinDef(
            join_fn=lambda a: (
                table("customer").alias("c"),
                and_(
                    _col("c.source_id")   == _col(f"{a}.source_id"),
                    _col("c.external_id") == _col(f"{a}.customer_id"),
                ),
            ),
            depends_on=[],
        ),
        "customer_tag": _JoinDef(
            join_fn=lambda a: (
                table("customer_tag").alias("ct"),
                and_(
                    _col("ct.source_id")   == _col(f"{a}.source_id"),
                    _col("ct.customer_id") == _col(f"{a}.customer_id"),
                ),
            ),
            depends_on=[],
        ),
    }

    _DIMS: ClassVar[dict[str, _DimDef]] = {
        "source_id":        _DimDef(lambda a: _col(f"{a}.source_id").label("source_id"),         lambda a: _col(f"{a}.source_id"),  []),
        "customer_id":      _DimDef(lambda a: _col(f"{a}.customer_id").label("customer_id"),     lambda a: _col(f"{a}.customer_id"),[]),
        "currency":         _DimDef(lambda a: _col(f"{a}.currency").label("currency"),           lambda a: _col(f"{a}.currency"),   []),
        "plan_id":          _DimDef(lambda a: _col("sub.plan_id").label("plan_id"),              lambda a: _col("sub.plan_id"),     ["subscription"]),
        "plan_interval":    _DimDef(lambda a: _col("p.interval").label("plan_interval"),         lambda a: _col("p.interval"),      ["subscription", "plan"]),
        "customer_country": _DimDef(lambda a: _col("c.country").label("customer_country"),       lambda a: _col("c.country"),       ["customer"]),
        "customer_tag":     _DimDef(lambda a: _col("ct.tag").label("customer_tag"),              lambda a: _col("ct.tag"),          ["customer_tag"]),
    }

    _FILTER_DEFS: ClassVar[dict[str, _FilterDef]] = {
        "source_ids":       _FilterDef(lambda a, pk: _col(f"{a}.source_id").in_(bindparam(pk, expanding=True)),       "source_ids",       [], lambda s: s.source_ids),
        "customer_ids":     _FilterDef(lambda a, pk: _col(f"{a}.customer_id").in_(bindparam(pk, expanding=True)),     "customer_ids",     [], lambda s: s.customer_ids),
        "currencies":       _FilterDef(lambda a, pk: _col(f"{a}.currency").in_(bindparam(pk, expanding=True)),        "currencies",       [], lambda s: s.currencies),
        "plan_ids":         _FilterDef(lambda a, pk: _col("sub.plan_id").in_(bindparam(pk, expanding=True)),          "plan_ids",         ["subscription"],         lambda s: s.plan_ids),
        "plan_intervals":   _FilterDef(lambda a, pk: _col("p.interval").in_(bindparam(pk, expanding=True)),           "plan_intervals",   ["subscription", "plan"], lambda s: s.plan_intervals),
        "customer_country": _FilterDef(lambda a, pk: _col("c.country").in_(bindparam(pk, expanding=True)),            "customer_country", ["customer"],             lambda s: s.customer_country),
        "customer_tags":    _FilterDef(lambda a, pk: _col("ct.tag").in_(bindparam(pk, expanding=True)),               "customer_tags",    ["customer_tag"],         lambda s: s.customer_tags),
    }

    # ------------------------------------------------------------------ #

    def __init__(
        self,
        base_table: str,
        alias: str = "m",
        available_joins: set[str] | None = None,
    ):
        """
        base_table:      table name, e.g. "metric_mrr_snapshot"
        alias:           SQL alias for the base table, e.g. "s"
        available_joins: restrict which joins may be added (None = all standard).
                         Pass a subset when the base table lacks certain FK columns
                         (e.g. metric_churn_event has no subscription_id).
                         Segment filters that require an unavailable join are
                         silently skipped; group_by dimensions raise ValueError.
        """
        self._a = alias
        self._available = available_joins
        self._stmt: Select = select().select_from(
            table(base_table).alias(alias)
        )
        self._needed_joins: set[str] = set()
        self._params: dict[str, Any] = {}

    # --- Fluent setters ------------------------------------------------ #

    def select(self, *exprs: ClauseElement) -> QueryBuilder:
        """Add SELECT column/aggregate expressions."""
        self._stmt = self._stmt.add_columns(*exprs)
        return self

    def where(self, condition: ClauseElement, **params) -> QueryBuilder:
        """Add a WHERE condition. Pass bind-param values as kwargs."""
        self._stmt = self._stmt.where(condition)
        self._params.update(params)
        return self

    def group_by(self, *exprs: ClauseElement) -> QueryBuilder:
        """Add fixed GROUP BY expressions (independent of SegmentFilter)."""
        self._stmt = self._stmt.group_by(*exprs)
        return self

    def order_by(self, *exprs: ClauseElement) -> QueryBuilder:
        self._stmt = self._stmt.order_by(*exprs)
        return self

    def apply_segment(self, segment: SegmentFilter | None) -> QueryBuilder:
        """
        Translate SegmentFilter into statement mutations:
        - Each active filter field → .where(condition) + mark required joins
        - Each group_by dimension  → .add_columns(label) + .group_by(col)
                                     + mark required joins

        Joins are not applied here; they are resolved and added in build()
        to ensure correct dependency order regardless of call sequence.
        """
        if not segment:
            return self

        for field_name, fdef in self._FILTER_DEFS.items():
            values = fdef.get_value(segment)
            if not values:
                continue
            if self._available is not None and not set(fdef.requires_joins) <= self._available:
                continue  # table lacks required FK — skip silently
            self._stmt = self._stmt.where(fdef.condition_fn(self._a, fdef.param_key))
            self._params[fdef.param_key] = values
            self._needed_joins.update(fdef.requires_joins)

        for dim in segment.group_by:
            if dim not in self._DIMS:
                raise ValueError(f"Unknown group_by dimension '{dim}'")
            ddef = self._DIMS[dim]
            if self._available is not None and not set(ddef.requires_joins) <= self._available:
                raise ValueError(
                    f"group_by='{dim}' requires joins {ddef.requires_joins!r} "
                    f"not available on this table"
                )
            self._stmt = self._stmt.add_columns(ddef.select_fn(self._a))
            self._stmt = self._stmt.group_by(ddef.group_by_fn(self._a))
            self._needed_joins.update(ddef.requires_joins)

        return self

    def build(self) -> tuple[Select, dict[str, Any]]:
        """
        Resolve pending joins in dependency order and return the finished
        Select statement together with the bind-params dict.

        Usage:
            stmt, params = builder.build()
            result = await db.execute(stmt, params)
        """
        stmt = self._stmt
        for jdef, tgt, on in self._resolve_joins():
            stmt = stmt.join(tgt, on)
        return stmt, self._params

    def _resolve_joins(self) -> list[tuple[_JoinDef, Any, ClauseElement]]:
        """Topological sort of needed joins; return (jdef, target, onclause) triples."""
        result: list[tuple[_JoinDef, Any, ClauseElement]] = []
        seen: set[str] = set()

        def add(key: str) -> None:
            if key in seen:
                return
            jdef = self._JOINS[key]
            for dep in jdef.depends_on:
                add(dep)
            tgt, on = jdef.join_fn(self._a)
            result.append((jdef, tgt, on))
            seen.add(key)

        for key in sorted(self._needed_joins):
            add(key)
        return result
```

## Dependencies

The `dependencies` property declares which other metrics must be initialized before this one. The engine performs a topological sort and injects resolved instances.

```python
@register
class RetentionMetric(Metric):
    name = "retention"
    dependencies = ["mrr"]   # NRR/GRR queries metric_mrr_movement

    def _init(self, db, connector, deps):
        self.db = db
        self.mrr = deps["mrr"]   # injected MRR metric instance

    async def query(self, params, segment=None):
        # Can await self.mrr.query(...) or query metric_mrr_movement directly
        ...


@register
class QuickRatioMetric(Metric):
    name = "quick_ratio"
    dependencies = ["mrr"]

    def _init(self, db, connector, deps):
        self.db = db
        self.mrr = deps["mrr"]

    async def query(self, params, segment=None):
        stmt, qparams = (
            QueryBuilder("metric_mrr_movement", alias="m")
            .select(
                _col("m.movement_type").label("movement_type"),
                func.sum(_col("m.amount_usd_cents")).label("total"),
            )
            .where(
                _col("m.occurred_at").between(bindparam("start"), bindparam("end")),
                start=params["start"], end=params["end"],
            )
            .group_by(_col("m.movement_type"))
            .apply_segment(segment)
            .build()
        )
        rows = (await self.db.execute(stmt, qparams)).all()

        growth = sum(r.total for r in rows if r.movement_type in ("new", "expansion", "reactivation"))
        loss   = abs(sum(r.total for r in rows if r.movement_type in ("churn", "contraction")))
        return growth / loss if loss > 0 else None
```

Dependency graph for built-in metrics:

```
mrr ──────────────────► retention (NRR/GRR)
  └──────────────────► quick_ratio
  └──────────────────► ltv (ARPU)
churn ─────────────► ltv (churn rate denominator)
```
