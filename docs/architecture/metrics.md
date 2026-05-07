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

from tidemill.metrics.query import Cube
from tidemill.segments.model import SegmentDef


@dataclass
class QuerySpec:
    """Declarative query specification resolved against a metric's Cube.

    Dimensions and filters reference names defined in the model (e.g., "plan_interval",
    "customer_country"). The model validates them and compiles to SQL via fragment
    composition. See [Cubes & Query Algebra](cubes.md) and [Segmentation](segments.md).

    Return shape:
    - dimensions set → list of dicts, one row per group
    - compare set   → list of dicts, one row per `segment_id` (ratio metrics
                      return per-segment numerator/denominator pairs already
                      divided — see "Compare-mode return shape" below)
    - otherwise     → scalar or time series
    """
    # Dimensions to group by (names from model.Dimensions)
    #   "plan_id"          — one row per plan
    #   "plan_interval"    — one row per billing interval (monthly/yearly/...)
    #   "customer_country" — one row per country
    #   "source_id"        — one row per billing source
    #   "currency"         — one row per currency (uses *_cents, not base-currency aggregate)
    #   "cohort_month"     — retention-specific: one row per cohort
    #   Computed dims from MRR cubes: "mrr_band", "arr_band", "tenure_months",
    #   "cohort_month" (CASE WHEN / DATE_TRUNC expressions)
    dimensions: list[str] = field(default_factory=list)

    # Filters: dimension_name → value (equality) or {op: value} for other operators
    #   {"customer_country": "US"}                    — equality
    #   {"plan_interval": {"in": ["monthly", "yearly"]}} — IN list
    filters: dict[str, Any] = field(default_factory=dict)

    # Time bucketing
    granularity: str | None = None        # day | week | month | quarter | year
    time_range: tuple[str, str] | None = None

    # Segmentation — see segments.md for the AST + compilation model
    #   segment  — a parsed SegmentDef applied as a universe filter (AND'd
    #              into every row, narrows the rowset for the whole query)
    #   compare  — list of (segment_id, SegmentDef) pairs; compile() emits a
    #              CROSS JOIN over a VALUES list of segment_ids and a compound
    #              OR predicate so each row is tagged with every branch it
    #              matches (overlapping segments produce duplicate rows, by
    #              design)
    segment: SegmentDef | None = None
    compare: tuple[tuple[str, SegmentDef], ...] | None = None


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

    @property
    def primary_cube(self) -> type[Cube]:
        """The cube exposed as this metric's filter / group-by surface.

        Used by the discovery endpoint (`GET /api/metrics/{name}/fields`)
        and the segment validator so generic routers don't have to
        hard-code which cube belongs to which metric. Defaults to
        `self.model`. Metrics with multiple cubes (e.g. churn — event +
        state) override to pick the one that carries the richest
        end-user filter set.
        """
        return self.model

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
from tidemill.metrics import register

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
class RetentionMetric(Metric):
    name = "retention"
    dependencies = ["mrr"]   # engine injects mrr metric at startup
    event_types = ["subscription.created", "subscription.activated",
                   "subscription.churned", "subscription.reactivated"]

    async def query(self, params, spec=None):
        # NRR / GRR query metric_mrr_movement directly; cohort matrix reads
        # metric_retention_cohort + metric_retention_activity.
        ...
```

The Quick Ratio is **not** a registered metric — it is a pure derivation from MRR movements. It lives in the reports layer as `tidemill.reports.mrr.quick_ratio(tm, start, end)` and in the summary endpoint's post-processing.

At startup, the engine:

1. Discovers all registered metrics
2. **Resolves dependency order** — topological sort of the dependency graph; raises on cycles
3. Initializes metrics in dependency order; injects resolved instances
4. Calls `register_tables()` on each — tables are added to the SQLAlchemy metadata
5. Runs Alembic migrations (or `metadata.create_all()` in dev)
6. **Ingestion mode only:** starts a Kafka consumer per metric (consumer group: `tidemill.metric.{name}`)

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

**Subscribes to (ingestion mode):** `subscription.created`, `subscription.activated`, `subscription.changed`, `subscription.canceled`, `subscription.churned`, `subscription.reactivated`, `subscription.paused`, `subscription.resumed`, `invoice.paid` (drives the trailing-3m usage component)

**Direct queries (same-database mode):** `DatabaseConnector.get_mrr_cents()`, `DatabaseConnector.get_subscription_changes()`

**Tables:**

```sql
-- Running MRR snapshot, updated on every subscription event
CREATE TABLE metric_mrr_snapshot (
    id              UUID PRIMARY KEY,
    source_id       UUID NOT NULL,
    customer_id     TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    -- Combined MRR = subscription_mrr + usage_mrr (kept for read efficiency).
    mrr_cents       BIGINT NOT NULL,
    mrr_base_cents   BIGINT NOT NULL,
    -- Component breakdown — subscription is licensed-recurring (Stripe
    -- non-metered items); usage is the trailing-3m smoothed metered charge.
    subscription_mrr_cents      BIGINT NOT NULL DEFAULT 0,
    subscription_mrr_base_cents BIGINT NOT NULL DEFAULT 0,
    usage_mrr_cents             BIGINT NOT NULL DEFAULT 0,
    usage_mrr_base_cents        BIGINT NOT NULL DEFAULT 0,
    currency        TEXT NOT NULL,           -- ISO 4217
    snapshot_at     TIMESTAMPTZ NOT NULL,
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
    -- Origin: 'subscription' (licensed-plan changes) or 'usage' (trailing-3m
    -- component shift). Lets the waterfall split deltas by source.
    source          TEXT NOT NULL DEFAULT 'subscription',
    amount_cents    BIGINT NOT NULL,
    amount_base_cents BIGINT NOT NULL,
    currency        TEXT NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL
);

-- Per-subscription monthly bucket of finalized usage charges. Trailing-3m
-- average of this table feeds metric_mrr_snapshot.usage_mrr_*. Also the
-- canonical store backing the usage_revenue metric.
CREATE TABLE metric_mrr_usage_component (
    id              UUID PRIMARY KEY,
    source_id       UUID NOT NULL,
    customer_id     TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    period_start    DATE NOT NULL,           -- first-of-month UTC
    usage_cents     BIGINT NOT NULL,
    usage_base_cents BIGINT NOT NULL,
    currency        TEXT NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL,
    UNIQUE(source_id, subscription_id, period_start)
);
```

**Usage component (trailing 3-month):** On every `invoice.paid` event, the MRR metric sums the invoice's `kind='usage'` line items into the bucket for that billing month, recomputes the trailing-3m mean for the subscription, and emits an `expansion`/`contraction` movement (tagged `source='usage'`) when the mean shifts. See `tidemill/metrics/mrr/usage.py` and `docs/definitions.md#mrr` for the formal definition. This is what makes pure-usage customers (e.g. the seeded "Active Starter" archetype) visible to downstream churn and LTV — without it they show $0 MRR and are invisible to logo-churn entirely.

**Event handling:**

```python
async def handle_event(self, event: Event) -> None:
    match event.type:
        case "subscription.created":
            # Snapshot only — "new" movement deferred to subscription.activated
            # to avoid double-counting trials that later convert.
            await self._upsert_snapshot(event, event.payload["mrr_cents"],
                                        event.payload["mrr_base_cents"])

        case "subscription.activated":
            await self._upsert_snapshot(event, event.payload["mrr_cents"],
                                        event.payload["mrr_base_cents"])
            await self._append_movement(event, "new", event.payload["mrr_cents"],
                                        event.payload["mrr_base_cents"])

        case "subscription.changed":
            prev, prev_usd = event.payload["prev_mrr_cents"], event.payload["prev_mrr_base_cents"]
            new,  new_usd  = event.payload["new_mrr_cents"],  event.payload["new_mrr_base_cents"]
            await self._upsert_snapshot(event, new, new_usd)
            delta, delta_usd = new - prev, new_usd - prev_usd
            kind = "expansion" if delta > 0 else "contraction"
            await self._append_movement(event, kind, delta, delta_usd)

        case "subscription.churned":
            prev, prev_usd = event.payload["prev_mrr_cents"], event.payload["prev_mrr_base_cents"]
            await self._upsert_snapshot(event, 0, 0)
            await self._append_movement(event, "churn", -prev, -prev_usd)

        case "subscription.reactivated":
            mrr, mrr_base = event.payload["mrr_cents"], event.payload["mrr_base_cents"]
            await self._upsert_snapshot(event, mrr, mrr_base)
            await self._append_movement(event, "reactivation", mrr, mrr_base)

        case "subscription.paused":
            mrr, mrr_base = event.payload["mrr_cents"], event.payload["mrr_base_cents"]
            await self._upsert_snapshot(event, 0, 0)
            await self._append_movement(event, "churn", -mrr, -mrr_base)

        case "subscription.resumed":
            mrr, mrr_base = event.payload["mrr_cents"], event.payload["mrr_base_cents"]
            await self._upsert_snapshot(event, mrr, mrr_base)
            await self._append_movement(event, "reactivation", mrr, mrr_base)
```

**Queries (dual-mode):**

```python
async def query(self, params: dict, spec=None) -> Any:
    match params.get("query_type"):
        case "current":
            if self.connector:
                # Same-database mode: query billing tables directly
                return await self.connector.get_mrr_base_cents(params.get("at"))
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
    q = measure + m.where("s.mrr_base_cents", ">", 0)

    # Time filter
    if at:
        q = q + m.filter("snapshot_at", "<=", at)

    # Apply user-requested dimensions, filters, segment (universe filter),
    # and compare (per-branch slicing) from spec.  build_spec_fragment is
    # the single bridge between QuerySpec and Cube — see
    # tidemill/segments/compiler.py.
    q = q + await build_spec_fragment(m, spec, self.db)

    stmt, params = q.compile(m)
    result = await self.db.execute(stmt, params)
    rows = result.mappings().all()

    # Scalar when no dimensions and no compare, list of dicts otherwise.
    has_compare = bool(spec and spec.compare)
    if not spec or (not spec.dimensions and not has_compare):
        return rows[0]["mrr"] if rows else 0
    return [dict(r) for r in rows]
```

**Example: SQL generated for `_current_mrr` with various specs**

No spec — plain aggregate:
```sql
SELECT SUM(s.mrr_base_cents) AS mrr
FROM metric_mrr_snapshot s
WHERE s.mrr_base_cents > 0
```

`QuerySpec(filters={"plan_interval": {"in": ["yearly"]}})` — filter only, no dimensions:
```sql
SELECT SUM(s.mrr_base_cents) AS mrr
FROM metric_mrr_snapshot s
  JOIN subscription sub ON sub.source_id = s.source_id AND sub.external_id = s.subscription_id
  JOIN plan p ON p.id = sub.plan_id
WHERE s.mrr_base_cents > 0
  AND p.interval = ANY(:plan_interval)
```

`QuerySpec(dimensions=["plan_interval", "customer_country"])` — dimensional cut:
```sql
SELECT p.interval AS plan_interval,
       c.country AS customer_country,
       SUM(s.mrr_base_cents) AS mrr
FROM metric_mrr_snapshot s
  JOIN subscription sub ON sub.source_id = s.source_id AND sub.external_id = s.subscription_id
  JOIN plan p ON p.id = sub.plan_id
  JOIN customer c ON c.source_id = s.source_id AND c.external_id = s.customer_id
WHERE s.mrr_base_cents > 0
GROUP BY p.interval, c.country
```

`QuerySpec(filters={"customer_country": {"in": ["US", "DE"]}}, dimensions=["plan_id"])` — filter + dimension:
```sql
SELECT sub.plan_id,
       SUM(s.mrr_base_cents) AS mrr
FROM metric_mrr_snapshot s
  JOIN subscription sub ON sub.source_id = s.source_id AND sub.external_id = s.subscription_id
  JOIN customer c ON c.source_id = s.source_id AND c.external_id = s.customer_id
WHERE s.mrr_base_cents > 0
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

    q = q + await build_spec_fragment(mm, spec, self.db)

    stmt, params = q.compile(mm)
    result = await self.db.execute(stmt, params)
    return [dict(r) for r in result.mappings().all()]
```

**Example: breakdown SQL with `QuerySpec(dimensions=["plan_id"])`:**
```sql
SELECT m.movement_type,
       sub.plan_id,
       SUM(m.amount_base_cents) AS amount_base
FROM metric_mrr_movement m
  JOIN subscription sub ON sub.source_id = m.source_id AND sub.external_id = m.subscription_id
WHERE m.occurred_at BETWEEN :start AND :end
GROUP BY m.movement_type, sub.plan_id
```

**Waterfall query — monthly MRR bridge:**

The waterfall builds a month-by-month bridge from starting MRR to ending MRR. It combines a baseline snapshot query with movement aggregation:

1. **Baseline** — query `metric_mrr_snapshot` for total MRR at the start of the range (same as `_current_mrr(start)`)
2. **Movements** — query `metric_mrr_movement` grouped by `date_trunc('month', occurred_at)` and `movement_type`
3. **Accumulate** — walk months in order; each month's `starting_mrr` = previous month's `ending_mrr`, `ending_mrr` = `starting_mrr` + sum of movements

```python
async def _mrr_waterfall(self, start: date, end: date, spec: QuerySpec | None):
    months = pd.date_range(start, end, freq="MS")
    baseline = await self._current_mrr(start, spec)    # step 1

    mm = self.movement_model  # MRRMovementCube
    q = (                                               # step 2
        mm.measures.amount
        + mm.dimension("movement_type")
        + mm.filter("occurred_at", "between", (start, end))
        + mm.time_grain("occurred_at", "month")
    )
    # ...execute and index by (month, movement_type)...

    waterfall = []                                      # step 3
    ending_mrr = baseline
    for month in months:
        starting_mrr = ending_mrr
        net_change = sum(movements for this month)
        ending_mrr = starting_mrr + net_change
        waterfall.append({month, starting_mrr, new, expansion,
                          contraction, churn, reactivation,
                          net_change, ending_mrr})
    return waterfall
```

The movement query SQL (step 2):

```sql
SELECT date_trunc('month', m.occurred_at) AS period,
       m.movement_type,
       SUM(m.amount_base_cents) AS amount_base
FROM metric_mrr_movement m
WHERE m.occurred_at BETWEEN :start AND :end
GROUP BY period, m.movement_type
```

Months with no movements appear with all-zero changes and MRR carried forward from the previous month.

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

-- Churn events for rate calculation. `cancel_reason` is copied from the
-- originating subscription.canceled / subscription.churned payload so the
-- event can be segmented by reason without re-joining the subscription
-- table (sourced from Stripe's `cancellation_details.feedback`).
CREATE TABLE metric_churn_event (
    id              UUID PRIMARY KEY,
    event_id        UUID NOT NULL UNIQUE,
    source_id       UUID NOT NULL,
    customer_id     TEXT NOT NULL,
    churn_type      TEXT NOT NULL,   -- logo | revenue | canceled
    cancel_reason   TEXT,            -- too_expensive | missing_features | …
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

Revenue churn rate (computed in base currency for cross-currency correctness):

```sql
SELECT
    ABS(SUM(CASE WHEN m.movement_type = 'churn' THEN m.amount_base_cents ELSE 0 END))::float
    /
    NULLIF((SELECT SUM(mrr_base_cents) FROM metric_mrr_snapshot WHERE snapshot_at < :start), 0)
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

**Subscribes to (ingestion mode):** `invoice.paid`

**Dependencies:** `mrr` (ARPU queries MRR snapshot), `churn` (simple LTV uses logo churn rate)

**Tables:**

```sql
-- Append-only log of paid invoices (idempotent via event_id)
CREATE TABLE metric_ltv_invoice (
    id                UUID PRIMARY KEY,
    event_id          UUID NOT NULL UNIQUE,   -- idempotency key
    source_id         UUID NOT NULL,
    customer_id       TEXT NOT NULL,
    amount_cents      BIGINT NOT NULL,        -- original currency
    amount_base_cents BIGINT NOT NULL,        -- base currency at FX rate on paid_at
    currency          TEXT NOT NULL,           -- ISO 4217
    paid_at           TIMESTAMPTZ NOT NULL
);
```

**Event handling:**

```python
async def handle_event(self, event: Event) -> None:
    # invoice.paid → insert with ON CONFLICT (event_id) DO NOTHING
    # Amount converted to base currency via FX module
```

**Queries:**

ARPU (queries via `MRRSnapshotCube` — the `customer_count` measure on that cube exists for this purpose):
```python
sm = MRRSnapshotCube
q = (
    sm.measures.mrr
    + sm.measures.customer_count
    + sm.where("s.mrr_base_cents", ">", 0)
)
if at:
    q = q + sm.filter("snapshot_at", "<=", at)
q = q + await build_spec_fragment(sm, spec, self.db)
```
```sql
SELECT SUM(s.mrr_base_cents) AS mrr,
       COUNT(DISTINCT s.customer_id) AS customer_count
FROM metric_mrr_snapshot AS s
WHERE s.mrr_base_cents > 0
```

Simple LTV: `ARPU / logo_churn_rate` — delegates to MRR (via `MRRSnapshotCube`) and Churn metrics.

Cohort LTV uses the same cohort definition as retention — *month of a
customer's first ``new`` MRR movement* — so the denominator matches ARPU
(both count customers with at least one active subscription, `MRR > 0`).
Trials that never convert are excluded.  Computed in two cube queries and
joined in Python:

1. `cohort_by_customer` from `MRRMovementCube` filtered to `movement_type = 'new'`,
   grouped by `customer_id` + month (take earliest month per customer).
2. `revenue_by_customer` from `LtvInvoiceCube` filtered to `paid_at BETWEEN :start AND :end`,
   grouped by `customer_id`.
3. Group by cohort month: `customer_count = |cohort|`,
   `total_revenue = SUM(invoices for cohort members)`.

**Cubes:**

- `LtvInvoiceCube` — measures: `total_revenue`, `total_revenue_original`, `invoice_count`, `customer_count`; dimensions: `source_id`, `customer_id`, `currency`, `customer_country` (via customer join), `cohort_month` (via retention cohort join, still available but unused for cohort LTV).
- `MRRMovementCube` — used by ARPU (`at` set) and Cohort LTV for movement-history queries.
- `MRRSnapshotCube` — used by ARPU (`at=None`) for current-state reads.

**API endpoints:** `GET /metrics/ltv` (simple), `GET /metrics/ltv/arpu`, `GET /metrics/ltv/cohort`

### Trials (P1)

**Subscribes to (ingestion mode):** `subscription.trial_started`, `subscription.trial_converted`, `subscription.trial_expired`

Trial metrics are **cohort-based**: a trial is attributed to the period of its `started_at`, and its converted/expired outcome rolls up to the same cohort regardless of when the outcome event arrives.  Late conversions retroactively update the cohort's rate.

**Tables:**

```sql
-- Append-only lifecycle log (audit / idempotent via event_id)
CREATE TABLE metric_trial_event (
    id              UUID PRIMARY KEY,
    event_id        UUID NOT NULL UNIQUE,
    source_id       UUID NOT NULL,
    customer_id     TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    event_type      TEXT NOT NULL,       -- started | converted | expired
    occurred_at     TIMESTAMPTZ NOT NULL
);

-- One row per trial.  Cohort queries aggregate over this table.
CREATE TABLE metric_trial (
    id              TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL,
    customer_id     TEXT NOT NULL,
    subscription_id TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL,
    converted_at    TIMESTAMPTZ,
    expired_at      TIMESTAMPTZ,
    CONSTRAINT uq_trial_sub UNIQUE (source_id, subscription_id)
);
```

**Event handling:**

```python
# subscription.trial_started   → upsert started_at (LEAST of existing/new)
# subscription.trial_converted → upsert converted_at (COALESCE — set once)
# subscription.trial_expired   → upsert expired_at   (COALESCE — set once)
# Each event is also appended to metric_trial_event (ON CONFLICT event_id DO NOTHING).
# Out-of-order events are safe: a converted/expired arriving before started
# inserts a placeholder row; the later started event corrects started_at.
```

**Queries:**

Funnel — a single aggregate over `metric_trial` filtered by `started_at`:
```python
q = (m.measures.started_count      # COUNT(*)
   + m.measures.converted_count    # COUNT(converted_at) — non-null
   + m.measures.expired_count      # COUNT(expired_at) — non-null
   + m.filter("started_at", "between", (start, end)))
```

Conversion rate — `converted / started` from the funnel result.

Series — same aggregate with `time_grain("started_at", interval)` → one row per cohort month.

**Cube:** `TrialCube` — source `metric_trial`; measures: `started_count`, `converted_count`, `expired_count`, `customer_count`; dimensions: `source_id`, `customer_country` (via customer join); time dimensions: `started_at`, `converted_at`, `expired_at`.

**API endpoints:** `GET /metrics/trials` (conversion rate), `GET /metrics/trials/series`, `GET /metrics/trials/funnel`

### Usage Revenue (P1)

Sibling metric to MRR. Reports the **raw** monthly usage charges as actuals — distinct from MRR's smoothed trailing-3m usage component. No event subscription: the canonical store (`metric_mrr_usage_component`) is populated by the MRR metric's `invoice.paid` handler. Usage Revenue declares no new tables and re-aggregates that data via its own Cube. Useful for auditing meter events, reconciling against Stripe invoices, and answering "how much did customers actually pay for usage in month $m$" without smoothing.

**Cube:** `UsageRevenueCube` — source `metric_mrr_usage_component`; measures: `revenue`, `revenue_original`, `subscription_count`, `customer_count`; dimensions: `source_id`, `customer_id`, `subscription_id`, `currency`, plan/product/customer joins, `tenure_months`, `cohort_month`; time dimension: `period_start`.

**Dependencies:** `mrr` — usage_revenue must initialize after MRR so the upstream `invoice.paid` handler is wired before any query runs.

**API endpoints:** `GET /metrics/usage-revenue` (total), `GET /metrics/usage-revenue/series`, `GET /metrics/usage-revenue/by-customer`

## MetricsEngine

The engine dynamically discovers and delegates to metrics. It has no hardcoded metric methods — every metric is reached through the registry.

```python
class MetricsEngine:
    def __init__(
        self,
        db: AsyncSession,
        metrics: list[Metric] | None = None,
    ):
        self.db = db
        # Auto-discover all @register metrics if none provided
        raw = metrics if metrics is not None else discover_metrics()
        # Resolve dependency order (topological sort); raises on cycles or missing deps
        ordered = resolve_dependencies(raw)
        # Initialize in order, injecting resolved instances
        # (synchronous — no I/O, just wiring)
        self._metrics: dict[str, Metric] = {}
        for m in ordered:
            deps = {name: self._metrics[name] for name in m.dependencies}
            m.init(db=db, deps=deps)
            self._metrics[m.name] = m

    async def query(
        self,
        metric: str,
        params: dict,
        spec: QuerySpec | None = None,
    ) -> Any:
        """Route a query to the named metric. Works for any registered metric —
        built-in or custom — without engine changes.

        spec is validated against the metric's Cube inside the metric's query
        methods. Invalid dimension/filter names raise ValueError with available
        options.
        """
        if metric not in self._metrics:
            raise KeyError(f"No metric registered for '{metric}'. "
                           f"Available: {sorted(self._metrics)}")
        return await self._metrics[metric].query(params, spec=spec)

    def available_metrics(self) -> list[str]:
        """Return names of all registered metrics. Synchronous."""
        return sorted(self._metrics)
```

Same-database mode (Lago / Kill Bill) is reached by passing a `DatabaseConnector` into the specific metric's constructor or `init()` — not via the engine. Each metric decides how to dispatch between ingestion-mode reads (SQL against `metric_*` tables) and direct-query mode (via its connector).

### Usage

```python
engine = MetricsEngine(db=async_session)

# Any registered metric, any params — always awaited
await engine.query("mrr", {"query_type": "current"})
await engine.query("mrr", {"query_type": "series", "start": date(2025,1,1), "end": date(2025,12,31), "interval": "month"})
await engine.query("churn", {"start": date(2026,1,1), "end": date(2026,2,28), "type": "revenue"})

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
# ['churn', 'ltv', 'mrr', 'retention', 'trials']
```

The same `engine.query()` call is used from FastAPI, CLI, and Jupyter. The HTTP API maps URL path segments to metric names, query parameters to `params`, and dimension/filter parameters to `QuerySpec`.

## Segmentation (QuerySpec)

`QuerySpec` carries four orthogonal slicing concerns:

1. **Filters** — restrict which rows are included (`filters` dict → WHERE clauses)
2. **Dimensional cuts** — split the result by named dimensions (`dimensions` list → GROUP BY)
3. **Segment** — universe filter from a saved `SegmentDef` (AND'd into every row)
4. **Compare** — list of `(segment_id, SegmentDef)` pairs producing one tagged row per matching branch (CROSS JOIN VALUES + compound OR)

All four reference dimension names defined in the metric's [Cube](cubes.md), or attribute keys / static joins routed through the [segment compiler](segments.md). Every metric's `query()` calls `await build_spec_fragment(cube, spec, self.db)` exactly once; that helper folds all four concerns into the QueryFragment.

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
| `mrr_band` / `arr_band` | CASE expression on `mrr_base_cents` | customer (for `c.created_at`) | Bucketed segmentation |
| `tenure_months` | `AGE(now, c.created_at)` | customer | Age cohorts |

Computed dimensions (`mrr_band`, `arr_band`, `tenure_months`, `cohort_month` on the MRR/Churn cubes; `customer_created_month` on `LtvInvoiceCube`) are SQL expressions on `Dim.column` — they appear in the `/fields` discovery endpoint alongside regular dimensions.

Multiple dimensions can be combined: `dimensions=["plan_interval", "customer_country"]` gives MRR for each interval × country combination.

### Compare-mode return shape (ratio metrics)

For aggregate metrics (MRR, MRR breakdown, MRR series), compare mode returns one row per `segment_id` with the metric's measures duplicated per branch — straight from the SQL.

For **ratio metrics** (logo / revenue churn rate, NRR / GRR, ARPU, simple LTV, trial conversion rate), the numerator and denominator are separate sub-queries — each one runs through `build_spec_fragment` so both pick up the same compare payload, then the metric divides per `segment_id` in Python and returns a list:

```python
[
    {"segment_id": "seg_a", "logo_churn_rate": 0.038, "churn_count": 12, "active_at_start": 320},
    {"segment_id": "seg_b", "logo_churn_rate": 0.057, "churn_count":  8, "active_at_start": 140},
]
```

`tidemill/metrics/churn/metric.py` is the reference — `_logo_churn`, `_revenue_churn`, `_active_at_start_count`, and `_mrr_at_start_per_segment` all accept the spec and return per-segment dicts when compare is set. The same pattern is used in `LtvMetric._historical_arpu`, `RetentionMetric._revenue_retention`, and `TrialsMetric._funnel`.

**Cohort-matrix caveat.** Per-segment retention matrices would be a 4-D result (cohort × active month × customer × segment); the chart can't consume it today. `RetentionMetric._cohort_matrix` and `LtvMetric._cohort_ltv` strip `compare` (via `_filter_only(spec)`) and treat compare like a plain segment list — the matrix renders the union of customers matching any branch.

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

All metrics build their SQL through cubes and composable query fragments (`tidemill/metrics/query.py`). Each metric declares a `Cube` that defines the available joins, measures, and dimensions for its fact table. Query methods compose immutable `QueryFragment` objects — each fragment carries column expressions, filters, and required joins. The compiler resolves joins in dependency order and emits a SQLAlchemy `Select`.

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
class LtvMetric(Metric):
    name = "ltv"
    model = LtvInvoiceCube
    dependencies = ["mrr", "churn"]     # ARPU reads MRR snapshot; simple LTV uses churn rate

    def init(self, *, db, deps):
        self.db = db
        self.mrr = deps["mrr"]
        self.churn = deps["churn"]

    async def query(self, params, spec=None):
        # ARPU: queries MRRSnapshotCube (mrr + customer_count measures).
        # Simple LTV: ARPU / logo_churn_rate — delegates to churn metric.
        # Cohort LTV: MRRMovementCube for cohort assignment + LtvInvoiceCube for revenue.
        ...
```

Dependency graph for built-in metrics:

```
mrr ──────────────────► retention (NRR/GRR query MRRSnapshotCube + MRRMovementCube)
  └──────────────────► ltv (ARPU queries MRRSnapshotCube.mrr + .customer_count)
churn ─────────────────► ltv (simple LTV = ARPU / logo churn rate)
```

Trials has no dependencies — it only processes its own events.

Quick Ratio is **not** a registered metric. It's a post-processing derivation over MRR movements, exposed via `tidemill.reports.mrr.quick_ratio` and surfaced in the `/api/metrics/summary` response.
