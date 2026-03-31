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
class QuerySpec:
    """Declarative query specification resolved against a metric's Cube.

    Dimensions and filters reference names defined in the model (e.g., "plan_interval",
    "customer_country"). The model validates them and compiles to SQL via fragment
    composition. See [Cubes & Query Algebra](cubes.md) for details.

    When dimensions is set, query() returns a list of dicts:
        [{"plan_interval": "monthly", "mrr": 4200.00}, ...]
    When dimensions is empty, query() returns a scalar or time series as usual.
    """
    # Dimensions to group by (names from model.Dimensions)
    #   "plan_id"          — one row per plan
    #   "plan_interval"    — one row per billing interval (monthly/yearly/...)
    #   "customer_country" — one row per country
    #   "source_id"        — one row per billing source
    #   "currency"         — one row per currency (uses *_cents, not USD aggregate)
    #   "cohort_month"     — retention-specific: one row per cohort
    dimensions: list[str] = field(default_factory=list)

    # Filters: dimension_name → value (equality) or {op: value} for other operators
    #   {"customer_country": "US"}                    — equality
    #   {"plan_interval": {"in": ["monthly", "yearly"]}} — IN list
    filters: dict[str, Any] = field(default_factory=dict)

    # Time bucketing
    granularity: str | None = None        # day | week | month | quarter | year
    time_range: tuple[str, str] | None = None


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
    async def query(self, params: dict, spec: QuerySpec | None = None) -> Any:
        """Answer a metric query.

        params: query-type-specific parameters (at, start, end, interval, ...)
        spec:   optional QuerySpec with dimensions and filters. Names reference
                the metric's Cube. All built-in metrics support this.

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

    async def query(self, params, spec=None):
        if self.connector:  # same-database mode (Lago/Kill Bill)
            return await self._query_direct(params, spec)
        # Ingestion mode (Stripe) — primary path
        return await self._query_materialized(params, spec)


@register
class QuickRatioMetric(Metric):
    name = "quick_ratio"
    dependencies = ["mrr"]   # engine injects mrr metric at startup
    event_types = []         # no direct event subscription — reads mrr tables

    async def query(self, params, spec=None):
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
async def query(self, params: dict, spec=None) -> Any:
    match params.get("query_type"):
        case "current":
            if self.connector:
                # Same-database mode: query billing tables directly
                return await self.connector.get_mrr_usd_cents(params.get("at"))
            # Ingestion mode (primary): query materialized metric_mrr_snapshot
            return await self._current_mrr(params.get("at"), spec)
        case "series":
            return await self._mrr_series(params["start"], params["end"],
                                          params["interval"], spec)
        case "breakdown":
            return await self._mrr_breakdown(params["start"], params["end"], spec)
        case "arr":
            return await self.query({**params, "query_type": "current"}, spec) * 12
```

**Query building with cubes and fragment composition:**

Each MRR query method composes `QueryFragment` objects from `MRRSnapshotCube` or `MRRMovementCube`. The model declares available joins, measures, and dimensions; fragments carry the required joins automatically. See [Cubes & Query Algebra](cubes.md) for the full approach.

```python
async def _current_mrr(self, at: date | None, spec: QuerySpec | None):
    # Use original-currency measure when caller groups by currency
    use_original = spec and "currency" in (spec.dimensions or [])
    m = self.model  # MRRSnapshotCube
    measure = m.measures.mrr_original if use_original else m.measures.mrr

    # Base: always-present fragments
    q = measure + m.where("s.mrr_usd_cents", ">", 0)

    # Time filter
    if at:
        q = q + m.filter("snapshot_at", "<=", at)

    # Apply user-requested dimensions and filters from spec
    if spec:
        q = q + m.apply_spec(spec)

    stmt, params = q.compile(m)
    result = await self.db.execute(stmt, params)
    rows = result.mappings().all()

    # Scalar when no dimensions, list of dicts when grouped
    if not spec or not spec.dimensions:
        return rows[0]["mrr"] if rows else 0
    return [dict(r) for r in rows]
```

**Example: SQL generated for `_current_mrr` with various specs**

No spec — plain aggregate:
```sql
SELECT SUM(s.mrr_usd_cents) / 100.0 AS mrr
FROM metric_mrr_snapshot s
WHERE s.mrr_usd_cents > 0
```

`QuerySpec(filters={"plan_interval": {"in": ["yearly"]}})` — filter only, no dimensions:
```sql
SELECT SUM(s.mrr_usd_cents) / 100.0 AS mrr
FROM metric_mrr_snapshot s
  JOIN subscription sub ON sub.source_id = s.source_id AND sub.external_id = s.subscription_id
  JOIN plan p ON p.id = sub.plan_id
WHERE s.mrr_usd_cents > 0
  AND p.interval = ANY(:plan_interval)
```

`QuerySpec(dimensions=["plan_interval", "customer_country"])` — dimensional cut:
```sql
SELECT p.interval AS plan_interval,
       c.country AS customer_country,
       SUM(s.mrr_usd_cents) / 100.0 AS mrr
FROM metric_mrr_snapshot s
  JOIN subscription sub ON sub.source_id = s.source_id AND sub.external_id = s.subscription_id
  JOIN plan p ON p.id = sub.plan_id
  JOIN customer c ON c.source_id = s.source_id AND c.external_id = s.customer_id
WHERE s.mrr_usd_cents > 0
GROUP BY p.interval, c.country
```

`QuerySpec(filters={"customer_country": {"in": ["US", "DE"]}}, dimensions=["plan_id"])` — filter + dimension:
```sql
SELECT sub.plan_id,
       SUM(s.mrr_usd_cents) / 100.0 AS mrr
FROM metric_mrr_snapshot s
  JOIN subscription sub ON sub.source_id = s.source_id AND sub.external_id = s.subscription_id
  JOIN customer c ON c.source_id = s.source_id AND c.external_id = s.customer_id
WHERE s.mrr_usd_cents > 0
  AND c.country = ANY(:customer_country)
GROUP BY sub.plan_id
```

**Breakdown query with fragment composition:**

```python
async def _mrr_breakdown(self, start: date, end: date, spec: QuerySpec | None):
    mm = self.movement_model  # MRRMovementCube

    q = (
        mm.measures.amount
        + mm.dimension("movement_type")
        + mm.filter("occurred_at", "between", (start, end))
    )

    if spec:
        q = q + mm.apply_spec(spec)

    stmt, params = q.compile(mm)
    result = await self.db.execute(stmt, params)
    return [dict(r) for r in result.mappings().all()]
```

**Example: breakdown SQL with `QuerySpec(dimensions=["plan_id"])`:**
```sql
SELECT m.movement_type,
       sub.plan_id,
       SUM(m.amount_usd_cents) / 100.0 AS amount_usd
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
        spec: QuerySpec | None = None,
    ) -> Any:
        """Route a query to the named metric. Works for any registered metric —
        built-in or custom — without engine changes.

        spec is validated against the metric's Cube before execution.
        Invalid dimension/filter names raise ValueError with available options.
        """
        if metric not in self._metrics:
            raise KeyError(f"No metric registered for '{metric}'. "
                           f"Available: {sorted(self._metrics)}")
        return await self._metrics[metric].query(params, spec=spec)

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

# With dimensions and filters via QuerySpec
spec = QuerySpec(
    dimensions=["plan_interval", "customer_country"],
    filters={"customer_country": "US"},
    granularity="month",
)
await engine.query("mrr", {"query_type": "current"}, spec=spec)

# Per-currency breakdown (uses original-currency amounts)
await engine.query("mrr", {"query_type": "current"},
                   spec=QuerySpec(dimensions=["currency"]))

# Synchronous — no I/O
engine.available_metrics()
# ['churn', 'ltv', 'mrr', 'quick_ratio', 'retention', 'trials']
```

The same `engine.query()` call is used from FastAPI, CLI, and Jupyter. The HTTP API maps URL path segments to metric names, query parameters to `params`, and dimension/filter parameters to `QuerySpec`.

## Segmentation (QuerySpec)

`QuerySpec` replaces the old hardcoded filter approach with a model-driven system. It does two things:

1. **Filters** — restrict which rows are included (`filters` dict → WHERE clauses)
2. **Dimensional cuts** — split the result by named dimensions (`dimensions` list → GROUP BY)

Both reference dimension names defined in the metric's [Cube](cubes.md). The model validates names at query time and resolves joins automatically.

### Available Dimensions

Each metric's cube declares which dimensions are available. Common dimensions across metric models:

| Dimension | Column | Join required | Example |
|-----------|--------|---------------|---------|
| `source_id` | fact table `source_id` | none | Multi-source deployments |
| `currency` | fact table `currency` | none | Per-currency amounts (uses `*_cents`) |
| `plan_id` | `sub.plan_id` | subscription | MRR per plan |
| `plan_interval` | `p.interval` | subscription → plan | Monthly vs. annual |
| `customer_country` | `c.country` | customer | Churn rate by country |
| `movement_type` | `m.movement_type` | none (MRR movement only) | MRR breakdown |
| `cohort_month` | `rc.cohort_month` | none (retention only) | Cohort matrix |

Multiple dimensions can be combined: `dimensions=["plan_interval", "customer_country"]` gives MRR for each interval × country combination.

### Return Shape

**With dimensions:**

```python
# engine.query("mrr", {"query_type": "current"}, spec=QuerySpec(dimensions=["plan_id"]))
[
    {"plan_id": "plan_starter",      "mrr": 2900.00},
    {"plan_id": "plan_professional", "mrr": 6320.00},
    {"plan_id": "plan_enterprise",   "mrr": 3230.00},
]

# dimensions=["plan_interval", "customer_country"]
[
    {"plan_interval": "monthly", "customer_country": "US", "mrr": 4100.00},
    {"plan_interval": "monthly", "customer_country": "DE", "mrr":  980.00},
    {"plan_interval": "yearly",  "customer_country": "US", "mrr": 5200.00},
    ...
]
```

**Without dimensions:** scalar or time-series as usual.

### Cubes & Query Algebra

All metrics build their SQL through cubes and composable query fragments (`subscriptions/metrics/query.py`). Each metric declares a `Cube` that defines the available joins, measures, and dimensions for its fact table. Query methods compose immutable `QueryFragment` objects — each fragment carries column expressions, filters, and required joins. The compiler resolves joins in dependency order and emits a SQLAlchemy `Select`.

See **[Cubes & Query Algebra](cubes.md)** for the full approach: model definitions, fragment algebra, compilation pipeline, and concrete models for all metric tables.

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

    async def query(self, params, spec=None):
        # Can await self.mrr.query(...) or query metric_mrr_movement directly
        ...


@register
class QuickRatioMetric(Metric):
    name = "quick_ratio"
    model = MRRMovementCube
    dependencies = ["mrr"]

    def _init(self, db, connector, deps):
        self.db = db
        self.mrr = deps["mrr"]

    async def query(self, params, spec=None):
        m = self.model  # MRRMovementCube

        q = (
            m.measures.amount
            + m.dimension("movement_type")
            + m.filter("occurred_at", "between", (params["start"], params["end"]))
        )

        if spec:
            q = q + m.apply_spec(spec)

        stmt, bind = q.compile(m)
        rows = (await self.db.execute(stmt, bind)).mappings().all()

        by_type = {r["movement_type"]: r["amount_usd"] for r in rows}
        growth = sum(by_type.get(t, 0) for t in ("new", "expansion", "reactivation"))
        loss   = abs(sum(by_type.get(t, 0) for t in ("churn", "contraction")))
        return growth / loss if loss else None
```

Dependency graph for built-in metrics:

```
mrr ──────────────────► retention (NRR/GRR)
  └──────────────────► quick_ratio
  └──────────────────► ltv (ARPU)
churn ─────────────► ltv (churn rate denominator)
```
