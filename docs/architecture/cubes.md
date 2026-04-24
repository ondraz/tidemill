# Cubes & Query Algebra

> Declarative query building: cubes define what's queryable, algebraic fragments compose queries.
> Last updated: April 2026

## Overview

Metric queries need to aggregate fact tables (e.g., `metric_mrr_snapshot`) while slicing and filtering by columns that live in other tables (plans, customers, subscriptions). The naive approach — procedurally building JOINs and WHERE clauses — leads to duplicated join logic across metrics and fragile SQL construction.

This module solves the problem with a hybrid of two patterns:

1. **Cube** — a class that declares all available joins, measures, and dimensions for a fact table. Defines *what's queryable* in one place.
2. **Algebraic Fragment Composition** — queries are built by combining immutable `QueryFragment` objects with `+`. Each fragment carries column expressions, filters, and required joins. Fragments compose freely — order doesn't matter.

The cube owns the *contract* (available dimensions, join paths, measure definitions). Fragments provide *composability* (metrics build queries by combining pieces conditionally). The compiler turns a composed fragment into a SQLAlchemy `Select`.

## Design Rationale

1. **Cube solves join resolution once.** Pre-defined dimensions mean no ambiguity. The model is the single source of truth for what's queryable per fact table.
2. **Fragment composition replaces procedural building.** Metrics declare *what* they need, not *how* to join. Conditional logic is clean: `q = base + (extra if condition else Fragment())`.
3. **SQL transparency comes free.** `compile()` produces both the SQLAlchemy `Select` and a formatted SQL string. Every metric result can carry its SQL for auditability — the project's core differentiator.
4. **Serializable query specs.** The API receives `{"dimensions": [...], "filters": {...}}` and the model validates + compiles it. No custom parsing.
5. **Each metric owns its cubes.** MRR defines `MRRSnapshotCube` and `MRRMovementCube`. Churn defines `ChurnEventCube`. No shared global registry — each cube is self-contained.

## Core Concepts

### Cube

A `Cube` is a class that declares everything needed to query a fact table with dimensional slicing. It contains four nested declarations:

- **Joins** — how to reach dimension tables from the fact table, with dependency ordering
- **Measures** — named aggregation expressions (`Sum`, `CountDistinct`, `Avg`, `Count`)
- **Dimensions** — named columns for GROUP BY, each declaring which join it requires
- **TimeDimensions** — time columns that support granularity truncation (`DATE_TRUNC`)

```python
class MRRSnapshotCube(Cube):
    """Cube for the MRR snapshot fact table."""
    __source__ = "metric_mrr_snapshot"
    __alias__ = "s"

    class Joins:
        subscription = Join("subscription", alias="sub",
            on="sub.source_id = s.source_id AND sub.external_id = s.subscription_id")
        plan = Join("plan", alias="p",
            on="p.id = sub.plan_id", depends_on=["subscription"])
        product = Join("product", alias="prod",
            on="prod.id = p.product_id", depends_on=["plan"])
        customer = Join("customer", alias="c",
            on="c.source_id = s.source_id AND c.external_id = s.customer_id")

    class Measures:
        mrr = Sum("s.mrr_base_cents")
        mrr_original = Sum("s.mrr_cents")       # in original currency
        count = CountDistinct("s.subscription_id")

    class Dimensions:
        source_id = Dim("s.source_id")
        currency = Dim("s.currency")
        plan_id = Dim("sub.plan_id", join="subscription")
        plan_name = Dim("p.name", join="plan")
        plan_interval = Dim("p.interval", join="plan")
        billing_scheme = Dim("p.billing_scheme", join="plan")   # per_unit | tiered
        usage_type = Dim("p.usage_type", join="plan")           # licensed | metered
        product_name = Dim("prod.name", join="product")         # via plan → product
        customer_country = Dim("c.country", join="customer")
        collection_method = Dim("sub.collection_method", join="subscription")
        cancel_at_period_end = Dim("sub.cancel_at_period_end", join="subscription")

    class TimeDimensions:
        snapshot_at = TimeDim("s.snapshot_at")
```

Key properties:

- **Join dependencies** — `plan` depends on `subscription`, `product` depends on `plan`. Requesting `product_name` automatically pulls in all three joins in the correct order.
- **Lazy joins** — only dimensions/filters that are actually used trigger their joins. A query with no plan dimensions never joins the `plan` table.
- **Introspection** — the model can list its available dimensions and measures at runtime, enabling API validation and documentation generation.

!!! note "Plan/product dimensions require plan ingestion"
    The MRR cubes declare `plan_id`, `plan_name`, `plan_interval`,
    `billing_scheme`, `usage_type`, and `product_name`, but these join
    through the `plan` (and `product`) table. The Stripe connector
    currently does **not** emit `plan.*` / `product.*` events, so
    `subscription.plan_id` is NULL for Stripe-sourced data and any query
    that references those dimensions returns zero rows. They will start
    populating once plan/product ingestion lands — the cube declarations
    are correct in advance. Same-database connectors (Lago, Kill Bill)
    that query the billing engine's own plan tables are not affected.

```python
MRRSnapshotCube.available_dimensions()
# ['billing_scheme', 'cancel_at_period_end', 'collection_method', 'currency',
#  'customer_country', 'plan_id', 'plan_interval', 'plan_name',
#  'product_name', 'source_id', 'usage_type']

MRRSnapshotCube.available_measures()
# ['mrr', 'mrr_original', 'count']

MRRSnapshotCube.available_time_dimensions()
# ['snapshot_at']
```

### QueryFragment

A `QueryFragment` is an immutable, composable description of a query piece. It carries what to SELECT, what to filter, and which joins are needed — but no SQL yet.

```python
@dataclass(frozen=True)
class QueryFragment:
    """Immutable query fragment. Fragments compose via + (monoid)."""
    source: str | None = None
    alias: str | None = None
    measures: tuple[MeasureExpr, ...] = ()
    dimensions: tuple[DimExpr, ...] = ()
    filters: tuple[FilterExpr, ...] = ()
    joins: frozenset[str] = frozenset()         # join names needed
    time_grain: TimeGrainExpr | None = None

    def __add__(self, other: QueryFragment) -> QueryFragment:
        """Merge two fragments. Joins are unioned, time_grain uses first non-None."""
        return QueryFragment(
            source=self.source or other.source,
            alias=self.alias or other.alias,
            measures=self.measures + other.measures,
            dimensions=self.dimensions + other.dimensions,
            filters=self.filters + other.filters,
            joins=self.joins | other.joins,
            time_grain=self.time_grain or other.time_grain,
        )
```

### Fragment Algebra

Fragments combine via `+` with these properties:

| Property | Meaning |
|----------|---------|
| **Associative** | `(a + b) + c == a + (b + c)` — grouping doesn't affect result |
| **Commutative** | `a + b == b + a` — order of composition doesn't matter |
| **Identity** | `QueryFragment() + x == x` — empty fragment changes nothing |

This makes fragments a **commutative monoid**, which means:

- You can store fragments in lists and `reduce()` them
- Conditional inclusion is trivial: `base + (f if condition else QueryFragment())`
- Order of adding dimensions/filters/measures never matters
- Fragments are independently testable

### Fragment Constructors

The cube provides factory methods that return fragments. Each method encapsulates the column expression *and* the joins required to resolve it:

```python
# Measure fragments — carry the aggregation expression
model.measures.mrr
# → QueryFragment(source="metric_mrr_snapshot", alias="s",
#                  measures=(MeasureExpr("SUM", "s.mrr_base_cents", label="mrr"),))

# Dimension fragments — carry column expression + required joins
model.dimension("plan_interval")
# → QueryFragment(dimensions=(DimExpr("p.interval", label="plan_interval"),),
#                  joins=frozenset({"subscription", "plan"}))

model.dimension("customer_country")
# → QueryFragment(dimensions=(DimExpr("c.country", label="customer_country"),),
#                  joins=frozenset({"customer"}))

# Filter fragments — carry predicate + required joins
model.filter("plan_interval", "=", "monthly")
# → QueryFragment(filters=(FilterExpr("p.interval", "=", "monthly"),),
#                  joins=frozenset({"subscription", "plan"}))

model.filter("customer_country", "in", ["US", "DE"])
# → QueryFragment(filters=(FilterExpr("c.country", "in", ["US", "DE"]),),
#                  joins=frozenset({"customer"}))

# Time grain fragment — carries DATE_TRUNC expression
model.time_grain("snapshot_at", "month")
# → QueryFragment(time_grain=TimeGrainExpr("s.snapshot_at", "month"))

# Raw filter on the source table (no join needed)
model.where("s.mrr_base_cents", ">", 0)
# → QueryFragment(filters=(FilterExpr("s.mrr_base_cents", ">", 0),))
```

### Compilation

`compile()` turns a composed `QueryFragment` into a SQLAlchemy `Select` statement and a bind-params dict. The compilation pipeline:

1. **FROM** — `SELECT ... FROM {source} AS {alias}`
2. **Resolve joins** — collect all join names from the fragment, topologically sort by `depends_on`, emit `JOIN` clauses. Deduplication is automatic (joins are a `frozenset`).
3. **Add time grain** — `DATE_TRUNC(granularity, column) AS period` in SELECT and GROUP BY (first so `period` leads the projection).
4. **Add dimensions** — column expressions in SELECT and GROUP BY.
5. **Add measures** — aggregation expressions in SELECT (`SUM(...)`, `COUNT(DISTINCT ...)`, `COUNT(...)`, `AVG(...)`).
6. **Add filters** — WHERE clauses with bound parameters.

There is no ORDER BY in the algebra — ordering is handled by the caller or by post-processing in the metric. Also note: aggregates are emitted as raw `SUM(col)` / `COUNT(DISTINCT col)` — no unit conversion happens in the compiler (cents-to-dollars is the caller's responsibility).

A `to_sql(model)` helper compiles the statement against the PostgreSQL dialect and inline-substitutes bind parameters, which is useful for notebooks and SQL logging.

## Concrete Cubes

These are the cubes for the project's [metric tables](database.md#metric-tables). Each maps a fact table to its available joins, measures, and dimensions. Every cube lives next to its metric (e.g., `tidemill/metrics/mrr/cubes.py`, `tidemill/metrics/churn/cubes.py`).

Dimensions sourced from Stripe API objects: Customer (`name`, `address.country`), Subscription (`status`, `collection_method`, `cancel_at_period_end`, `cancellation_details`), Price/Plan (`interval`, `interval_count`, `billing_scheme`, `usage_type`), Product (`name`). See [Stripe API mapping](#stripe-api-mapping) below for the full field comparison.

### MRR Snapshot Cube

```python
class MRRSnapshotCube(Cube):
    """Current MRR per subscription. Updated on every subscription event."""
    __source__ = "metric_mrr_snapshot"
    __alias__ = "s"

    class Joins:
        subscription = Join("subscription", alias="sub",
            on="sub.source_id = s.source_id AND sub.external_id = s.subscription_id")
        plan = Join("plan", alias="p",
            on="p.id = sub.plan_id", depends_on=["subscription"])
        product = Join("product", alias="prod",
            on="prod.id = p.product_id", depends_on=["plan"])
        customer = Join("customer", alias="c",
            on="c.source_id = s.source_id AND c.external_id = s.customer_id")

    class Measures:
        mrr = Sum("s.mrr_base_cents", label="mrr")
        mrr_original = Sum("s.mrr_cents", label="mrr_original")
        count = CountDistinct("s.subscription_id", label="subscription_count")
        customer_count = CountDistinct("s.customer_id", label="customer_count")

    class Dimensions:
        source_id = Dim("s.source_id")
        currency = Dim("s.currency")
        # Plan (subscription → plan)
        plan_id = Dim("sub.plan_id", join="subscription")
        plan_name = Dim("p.name", join="plan", label="plan_name")
        plan_interval = Dim("p.interval", join="plan", label="plan_interval")
        billing_scheme = Dim("p.billing_scheme", join="plan")       # per_unit | tiered
        usage_type = Dim("p.usage_type", join="plan")               # licensed | metered
        # Product (subscription → plan → product)
        product_name = Dim("prod.name", join="product", label="product_name")
        # Customer
        customer_name = Dim("c.name", join="customer", label="customer_name")
        customer_country = Dim("c.country", join="customer", label="customer_country")
        # Subscription attributes
        collection_method = Dim("sub.collection_method", join="subscription")
        cancel_at_period_end = Dim("sub.cancel_at_period_end", join="subscription")

    class TimeDimensions:
        snapshot_at = TimeDim("s.snapshot_at")
```

The `customer_count` measure exists so LTV/ARPU queries can compute `SUM(mrr) / COUNT(DISTINCT customer_id)` in a single trip to the DB.

### MRR Movement Cube

```python
class MRRMovementCube(Cube):
    """Append-only log of MRR changes. Used for breakdown and time-series queries."""
    __source__ = "metric_mrr_movement"
    __alias__ = "m"

    class Joins:
        subscription = Join("subscription", alias="sub",
            on="sub.source_id = m.source_id AND sub.external_id = m.subscription_id")
        plan = Join("plan", alias="p",
            on="p.id = sub.plan_id", depends_on=["subscription"])
        product = Join("product", alias="prod",
            on="prod.id = p.product_id", depends_on=["plan"])
        customer = Join("customer", alias="c",
            on="c.source_id = m.source_id AND c.external_id = m.customer_id")

    class Measures:
        amount = Sum("m.amount_base_cents", label="amount_base")
        amount_original = Sum("m.amount_cents", label="amount_original")
        count = CountDistinct("m.event_id", label="event_count")

    class Dimensions:
        source_id = Dim("m.source_id")
        customer_id = Dim("m.customer_id")
        currency = Dim("m.currency")
        movement_type = Dim("m.movement_type")
        plan_id = Dim("sub.plan_id", join="subscription")
        plan_name = Dim("p.name", join="plan", label="plan_name")
        plan_interval = Dim("p.interval", join="plan", label="plan_interval")
        billing_scheme = Dim("p.billing_scheme", join="plan")
        usage_type = Dim("p.usage_type", join="plan")
        product_name = Dim("prod.name", join="product", label="product_name")
        customer_name = Dim("c.name", join="customer", label="customer_name")
        customer_country = Dim("c.country", join="customer", label="customer_country")
        collection_method = Dim("sub.collection_method", join="subscription")

    class TimeDimensions:
        occurred_at = TimeDim("m.occurred_at")
```

### Churn Customer State Cube

```python
class ChurnCustomerStateCube(Cube):
    """Active/churned state per customer. Updated by subscription events."""
    __source__ = "metric_churn_customer_state"
    __alias__ = "cs"

    class Joins:
        customer = Join("customer", alias="c",
            on="c.source_id = cs.source_id AND c.external_id = cs.customer_id")

    class Measures:
        count = CountDistinct("cs.customer_id", label="customer_count")

    class Dimensions:
        source_id = Dim("cs.source_id")
        customer_id = Dim("cs.customer_id")
        customer_name = Dim("c.name", join="customer", label="customer_name")
        customer_country = Dim("c.country", join="customer", label="customer_country")

    class TimeDimensions:
        first_active_at = TimeDim("cs.first_active_at")
        churned_at = TimeDim("cs.churned_at")
```

### Churn Event Cube

```python
class ChurnEventCube(Cube):
    """Individual churn events for rate calculation."""
    __source__ = "metric_churn_event"
    __alias__ = "ce"

    class Joins:
        customer = Join("customer", alias="c",
            on="c.source_id = ce.source_id AND c.external_id = ce.customer_id")
        customer_state = Join("metric_churn_customer_state", alias="cs",
            on="cs.source_id = ce.source_id AND cs.customer_id = ce.customer_id")

    class Measures:
        count = Count("*", label="churn_count")
        revenue_lost = Sum("ce.mrr_cents", label="revenue_lost")

    class Dimensions:
        source_id = Dim("ce.source_id")
        customer_id = Dim("ce.customer_id")
        churn_type = Dim("ce.churn_type")
        cancel_reason = Dim("ce.cancel_reason")               # from cancellation_details.feedback; populated on logo, revenue, and canceled rows
        customer_name = Dim("c.name", join="customer", label="customer_name")
        customer_country = Dim("c.country", join="customer", label="customer_country")
        # Scopes churn events to customers active at period start
        customer_first_active = Dim("cs.first_active_at", join="customer_state",
            label="customer_first_active")

    class TimeDimensions:
        occurred_at = TimeDim("ce.occurred_at")
```

The `customer_state` join plus the `customer_first_active` dimension let the churn metric restrict events to customers who were already active before the measurement window — essential for correct logo-churn denominators.

### Retention Cohort Cube

```python
class RetentionCohortCube(Cube):
    """Cohort membership and monthly activity for retention analysis."""
    __source__ = "metric_retention_cohort"
    __alias__ = "rc"

    class Joins:
        activity = Join("metric_retention_activity", alias="ra",
            on="ra.customer_id = rc.customer_id AND ra.source_id = rc.source_id")
        customer = Join("customer", alias="c",
            on="c.source_id = rc.source_id AND c.external_id = rc.customer_id")

    class Measures:
        cohort_size = CountDistinct("rc.customer_id", label="cohort_size")
        active_count = CountDistinct("ra.customer_id", label="active_count")

    class Dimensions:
        source_id = Dim("rc.source_id")
        customer_id = Dim("rc.customer_id")
        cohort_month = Dim("rc.cohort_month")
        active_month = Dim("ra.active_month", join="activity")
        customer_country = Dim("c.country", join="customer", label="customer_country")

    class TimeDimensions:
        cohort_month_time = TimeDim("rc.cohort_month")
```

### LTV Invoice Cube

```python
class LtvInvoiceCube(Cube):
    """Append-only log of paid invoices. Used for cohort LTV and revenue tracking."""
    __source__ = "metric_ltv_invoice"
    __alias__ = "li"

    class Joins:
        customer = Join("customer", alias="c",
            on="c.source_id = li.source_id AND c.external_id = li.customer_id")
        cohort = Join("metric_retention_cohort", alias="rc",
            on="rc.source_id = li.source_id AND rc.customer_id = li.customer_id")

    class Measures:
        total_revenue = Sum("li.amount_base_cents", label="total_revenue")
        total_revenue_original = Sum("li.amount_cents", label="total_revenue_original")
        invoice_count = Count("*", label="invoice_count")
        customer_count = CountDistinct("li.customer_id", label="customer_count")

    class Dimensions:
        source_id = Dim("li.source_id")
        customer_id = Dim("li.customer_id")
        currency = Dim("li.currency")
        customer_country = Dim("c.country", join="customer", label="customer_country")
        cohort_month = Dim("rc.cohort_month", join="cohort", label="cohort_month")

    class TimeDimensions:
        paid_at = TimeDim("li.paid_at")
```

The `cohort` join reaches `metric_retention_cohort` — the same table used by the retention metric — so LTV and retention share cohort definitions. Cohort LTV currently computes cohort membership in Python (`movement_type = 'new'` in `MRRMovementCube`) for flexibility; the `cohort_month` dimension is available but unused by the default cohort-LTV query.

### Trial Cube

```python
class TrialCube(Cube):
    """Per-trial outcomes. Cohort = month of started_at."""
    __source__ = "metric_trial"
    __alias__ = "t"

    class Joins:
        customer = Join("customer", alias="c",
            on="c.source_id = t.source_id AND c.external_id = t.customer_id")

    class Measures:
        # count(*) counts all rows; count(col) counts non-null values.
        # Every row has started_at, so started_count == count(*).
        started_count = Count("*", label="started")
        converted_count = Count("t.converted_at", label="converted")
        expired_count = Count("t.expired_at", label="expired")
        customer_count = CountDistinct("t.customer_id", label="customer_count")

    class Dimensions:
        source_id = Dim("t.source_id")
        customer_country = Dim("c.country", join="customer", label="customer_country")

    class TimeDimensions:
        started_at = TimeDim("t.started_at")
        converted_at = TimeDim("t.converted_at")
        expired_at = TimeDim("t.expired_at")
```

Trial metrics are **cohort-based**: the funnel measures (`started`, `converted`, `expired`) are derived from `COUNT(*)` and `COUNT(<timestamp>)` over the same row set, filtered by `started_at`. A trial that starts in January and converts in March is attributed to the January cohort regardless of when the conversion lands.

## Stripe API Mapping

The table below maps Stripe API fields to our schema columns and cube dimensions. Fields marked with **dim** are exposed as queryable dimensions in the cubes above.

### Customer → `customer` table

| Stripe field | Our column | Cube dimension | Notes |
|---|---|---|---|
| `id` | `external_id` | — | Stripe customer ID |
| `name` | `name` | — | |
| `email` | `email` | — | |
| `address.country` | `country` | **`customer_country`** | ISO 3166-1 alpha-2 |
| `currency` | `currency` | **`currency`** | Default billing currency |
| `created` | `created_at` | — | Cohort assignment |
| `metadata` | `metadata` | — | Custom business dimensions (JSONB) |
| `delinquent` | — | — | Could add for payment health segmentation |
| `address.state/city` | — | — | Sub-national geo; use metadata if needed |

### Product → `product` table (new)

| Stripe field | Our column | Cube dimension | Notes |
|---|---|---|---|
| `id` | `external_id` | — | Stripe product ID |
| `name` | `name` | **`product_name`** | Product-level MRR/churn analysis |
| `active` | `active` | — | |
| `metadata` | `metadata` | — | Product line, category |

### Price/Plan → `plan` table

| Stripe field | Our column | Cube dimension | Notes |
|---|---|---|---|
| `id` | `external_id` | **`plan_id`** | Stripe price/plan ID |
| `product` | `product_id` | (via product join) | FK to product table |
| `nickname` / `product.name` | `name` | **`plan_name`** | Human-readable plan name |
| `recurring.interval` | `interval` | **`plan_interval`** | month, year, week, day |
| `recurring.interval_count` | `interval_count` | — | 1=monthly, 3=quarterly, 12=annual |
| `unit_amount` | `amount_cents` | — | Per-unit price |
| `currency` | `currency` | — | |
| `billing_scheme` | `billing_scheme` | **`billing_scheme`** | per_unit, tiered |
| `recurring.usage_type` | `usage_type` | **`usage_type`** | licensed, metered |
| `type` | — | — | one_time vs recurring; filter at ingest |
| `trial_period_days` | `trial_period_days` | — | |
| `tiers` | — | — | Tiered pricing detail; store in metadata |
| `metadata` | `metadata` | — | Custom plan attributes |

### Subscription → `subscription` table

| Stripe field | Our column | Cube dimension | Notes |
|---|---|---|---|
| `id` | `external_id` | — | Stripe subscription ID |
| `status` | `status` | — | active, trialing, past_due, canceled, etc. |
| `items[].price × quantity` | `mrr_cents` / `mrr_base_cents` | (measure) | Computed at ingest time |
| `items[].quantity` | `quantity` | — | Seat/unit count |
| `currency` | `currency` | — | |
| `collection_method` | `collection_method` | **`collection_method`** | charge_automatically, send_invoice |
| `cancel_at_period_end` | `cancel_at_period_end` | **`cancel_at_period_end`** | Churn early warning |
| `cancellation_details.reason` | `cancel_reason` | — | customer, payment_failure, etc. |
| `cancellation_details.feedback` | `cancel_feedback` | — | too_expensive, missing_features, etc. |
| `start_date` | `started_at` | — | |
| `trial_start` / `trial_end` | `trial_start` / `trial_end` | — | |
| `canceled_at` | `canceled_at` | — | |
| `ended_at` | `ended_at` | — | |
| `current_period_start/end` | `current_period_start/end` | — | |
| `metadata` | — | — | Store in event payload |

### Churn Events → `metric_churn_event` table

| Stripe field | Our column | Cube dimension | Notes |
|---|---|---|---|
| `cancellation_details.reason` | `cancel_reason` | **`cancel_reason`** | Denormalized from subscription for direct churn analysis |

### Not captured (available via metadata or future extension)

| Stripe field | Analytics value | Priority |
|---|---|---|
| `charge.payment_method_details.card.brand` | Payment success by card brand | P1 |
| `charge.payment_method_details.card.country` | Card issuing country vs billing country | P1 |
| `charge.outcome.risk_level` | Fraud/risk segmentation | P2 |
| `invoice.billing_reason` | Distinguish cycle vs proration vs manual | P1 |
| `invoice.amount_paid` / `amount_remaining` | AR aging, collection rate | P1 |
| `invoice.total_discount_amounts` | Discount impact on revenue | P2 |
| `customer.delinquent` | Payment health flag | P2 |
| `price.tiers` / `tiers_mode` | Tiered pricing analysis | P2 |

## Usage in Metrics

Metrics declare which cube they use. The `query()` method composes fragments from the model based on the incoming `QuerySpec`:

```python
@register
class MrrMetric(Metric):
    model = MRRSnapshotCube
    movement_model = MRRMovementCube

    async def query(self, params: dict, spec: QuerySpec | None = None) -> Any:
        match params.get("query_type"):
            case "current":
                return await self._current_mrr(params.get("at"), spec)
            case "series":
                return await self._mrr_series(
                    params["start"], params["end"], params["interval"], spec)
            case "breakdown":
                return await self._mrr_breakdown(params["start"], params["end"], spec)

    async def _current_mrr(self, at: date | None, spec: QuerySpec | None):
        # Choose original-currency measure when caller groups by currency
        use_original = spec and "currency" in (spec.dimensions or [])
        m = self.model
        measure = m.measures.mrr_original if use_original else m.measures.mrr

        # Base: always-present fragments
        q = measure + m.where("s.mrr_base_cents", ">", 0)

        # Time filter
        if at:
            q = q + m.filter("snapshot_at", "<=", at)

        # Apply user-requested dimensions and filters from spec
        if spec:
            q = q + m.apply_spec(spec)

        stmt, params = q.compile(m)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        if not spec or not spec.dimensions:
            return rows[0]["mrr"] if rows else 0
        return [dict(r) for r in rows]

    async def _mrr_breakdown(self, start: date, end: date, spec: QuerySpec | None):
        mm = self.movement_model

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

### Reusable Fragments

Common filter combinations can be stored as named fragments and reused across metrics:

```python
# Shared fragment: active subscriptions only
ACTIVE_ONLY = MRRSnapshotCube.where("s.mrr_base_cents", ">", 0)

# Shared fragment: monthly plans
MONTHLY_PLANS = MRRSnapshotCube.filter("plan_interval", "=", "monthly")

# Compose freely
q = MRRSnapshotCube.measures.mrr + ACTIVE_ONLY + MONTHLY_PLANS
```

### QuickRatio Example

The QuickRatio metric composes fragments from the MRR movement model:

```python
@register
class QuickRatioMetric(Metric):
    model = MRRMovementCube
    dependencies = ["mrr"]

    async def query(self, params: dict, spec: QuerySpec | None = None) -> Any:
        m = self.model

        q = (
            m.measures.amount
            + m.dimension("movement_type")
            + m.filter("occurred_at", "between", (params["start"], params["end"]))
        )

        if spec:
            q = q + m.apply_spec(spec)

        stmt, bind = q.compile(m)
        rows = (await self.db.execute(stmt, bind)).mappings().all()

        by_type = {r["movement_type"]: r["amount_base"] for r in rows}
        growth = sum(by_type.get(t, 0) for t in ("new", "expansion", "reactivation"))
        loss = abs(sum(by_type.get(t, 0) for t in ("churn", "contraction")))
        return growth / loss if loss else None
```

## QuerySpec

`QuerySpec` is the external API contract — what FastAPI/CLI users pass in. It references dimension and filter names from the metric's cube:

```python
@dataclass
class QuerySpec:
    """Declarative query specification. Validated against the metric's Cube."""

    # Dimensions to group by (names from model.Dimensions)
    dimensions: list[str] = field(default_factory=list)

    # Filters: dimension_name → value (equality) or {op: value}
    filters: dict[str, Any] = field(default_factory=dict)

    # Time bucketing
    granularity: str | None = None        # day | week | month | quarter | year
    time_range: tuple[str, str] | None = None
```

The model's `apply_spec()` method translates a `QuerySpec` into a composed fragment. Validation happens inside `Cube.dimension()`, `Cube.filter()`, and `Cube.time_grain()` — each raises `ValueError` with the list of available names when given an unknown one.

```python
@classmethod
def apply_spec(cls, spec: QuerySpec | None) -> QueryFragment:
    """Translate a QuerySpec into a composed QueryFragment."""
    if spec is None:
        return QueryFragment()

    result = QueryFragment()

    for dim_name in spec.dimensions or []:
        result = result + cls.dimension(dim_name)

    for field_name, value in (spec.filters or {}).items():
        if isinstance(value, dict):
            op = next(iter(value))
            result = result + cls.filter(field_name, op, value[op])
        else:
            result = result + cls.filter(field_name, "=", value)

    if spec.granularity:
        time_dims = sorted(cls._time_dimensions)
        if time_dims:
            result = result + cls.time_grain(time_dims[0], spec.granularity)

    return result
```

## API Integration

The REST API receives a JSON query spec and delegates to the engine:

```json
POST /api/metrics/mrr
{
    "query_type": "current",
    "dimensions": ["plan_interval", "customer_country"],
    "filters": {"customer_country": "US"},
    "granularity": "month"
}
```

FastAPI translates this to:

```python
spec = QuerySpec(
    dimensions=["plan_interval", "customer_country"],
    filters={"customer_country": "US"},
    granularity="month",
)
result = await engine.query("mrr", {"query_type": "current"}, spec=spec)
```

The model validates dimension/filter names before compilation. Invalid names produce clear error messages:

```
ValueError: Unknown dimension 'plan_name'. Available: ['currency', 'customer_country', 'plan_id', 'plan_interval', 'source_id']
```

## SQL Examples

Money values are stored as cents (integer); the compiler does not divide — cents-to-dollars conversion is the caller's responsibility.

### No spec — plain aggregate

```python
q = model.measures.mrr + model.where("s.mrr_base_cents", ">", 0)
```

```sql
SELECT SUM(s.mrr_base_cents) AS mrr
FROM metric_mrr_snapshot s
WHERE s.mrr_base_cents > 0
```

### Filter only (no dimensions)

```python
q = model.measures.mrr + model.where("s.mrr_base_cents", ">", 0) + model.filter("plan_interval", "=", "yearly")
```

```sql
SELECT SUM(s.mrr_base_cents) AS mrr
FROM metric_mrr_snapshot s
  JOIN subscription sub ON sub.source_id = s.source_id
                       AND sub.external_id = s.subscription_id
  JOIN plan p ON p.id = sub.plan_id
WHERE s.mrr_base_cents > 0
  AND p.interval = :plan_interval
```

### Dimensional cut

```python
q = (model.measures.mrr + model.where("s.mrr_base_cents", ">", 0)
     + model.dimension("plan_interval") + model.dimension("customer_country"))
```

```sql
SELECT p.interval AS plan_interval,
       c.country AS customer_country,
       SUM(s.mrr_base_cents) AS mrr
FROM metric_mrr_snapshot s
  JOIN subscription sub ON sub.source_id = s.source_id
                       AND sub.external_id = s.subscription_id
  JOIN plan p ON p.id = sub.plan_id
  JOIN customer c ON c.source_id = s.source_id
                 AND c.external_id = s.customer_id
WHERE s.mrr_base_cents > 0
GROUP BY p.interval, c.country
```

### Filter + dimension + time grain

```python
q = (model.measures.mrr + model.where("s.mrr_base_cents", ">", 0)
     + model.filter("customer_country", "in", ["US", "DE"])
     + model.dimension("plan_id")
     + model.time_grain("snapshot_at", "month"))
```

```sql
SELECT DATE_TRUNC('month', s.snapshot_at) AS period,
       sub.plan_id,
       SUM(s.mrr_base_cents) AS mrr
FROM metric_mrr_snapshot s
  JOIN subscription sub ON sub.source_id = s.source_id
                       AND sub.external_id = s.subscription_id
  JOIN customer c ON c.source_id = s.source_id
                 AND c.external_id = s.customer_id
WHERE s.mrr_base_cents > 0
  AND c.country IN :customer_country
GROUP BY DATE_TRUNC('month', s.snapshot_at), sub.plan_id
```

### MRR breakdown by movement type + plan

```python
mm = MRRMovementCube
q = (mm.measures.amount + mm.dimension("movement_type") + mm.dimension("plan_id")
     + mm.filter("occurred_at", "between", (start, end)))
```

```sql
SELECT m.movement_type,
       sub.plan_id,
       SUM(m.amount_base_cents) AS amount_base
FROM metric_mrr_movement m
  JOIN subscription sub ON sub.source_id = m.source_id
                       AND sub.external_id = m.subscription_id
WHERE m.occurred_at BETWEEN :occurred_at_start AND :occurred_at_end
GROUP BY m.movement_type, sub.plan_id
```

`between` binds two parameters using the dimension name as the prefix (here `occurred_at_start` / `occurred_at_end`). Equality and `in` filters use `:<dimension_name>`; other raw `where(...)` calls derive a parameter name from the column and operator (e.g. `s_mrr_base_cents_gt`).

### Date-range semantics

All date ranges are **closed-closed** `[start, end]` — both endpoints are inclusive (see `docs/definitions.md#date-range-convention`). When a bare `date` is passed as a filter value, the filter layer coerces it to the appropriate day boundary so SQL `BETWEEN` captures the full calendar day against a `TIMESTAMPTZ` column:

- `between (start, end)` → `start` is pinned to `00:00:00.000000`, `end` to `23:59:59.999999`
- `<=` upper bound → coerced to end-of-day (inclusive)
- `<`, `>`, `>=` — no coercion; the bare date sits at `00:00:00` and behaves as the half-open boundary you'd expect

So `between (date(2025, 7, 1), date(2025, 9, 30))` covers every event from Jul 1 midnight through the last microsecond of Sep 30.

## Implementation Notes

### File Location

The cube machinery lives in `tidemill/metrics/query.py` — the same file that metrics import from. The concrete cubes are defined alongside their metrics (e.g., `MRRSnapshotCube` in `tidemill/metrics/mrr/cubes.py`).

### Package Structure

```
tidemill/metrics/
├── __init__.py          # re-exports Metric, QuerySpec, register, ...
├── base.py              # Metric ABC + QuerySpec
├── query.py             # Cube, QueryFragment, compilation
├── registry.py          # @register decorator, discovery, dependency resolution
├── route_helpers.py     # Shared FastAPI helpers (parse_spec, query_metric)
├── mrr/                 # MRRSnapshotCube, MRRMovementCube, MrrMetric, routes
├── churn/               # ChurnCustomerStateCube, ChurnEventCube, ChurnMetric, routes
├── retention/           # RetentionCohortCube, RetentionMetric, routes
├── ltv/                 # LtvInvoiceCube, LtvMetric, routes
└── trials/              # TrialCube, TrialsMetric, routes
```

Each metric subpackage contains `cubes.py`, `metric.py`, `routes.py`, `tables.py`, and `__init__.py`.

### SQLAlchemy Integration

All compilation targets SQLAlchemy Core's `Select` object — no string concatenation. The compiled statement is executed via `AsyncSession.execute(stmt, params)`, consistent with the project's async-everywhere convention.

### Adding a New Dimension

To make a new column queryable:

1. Add the join (if the table isn't already reachable) to the model's `Joins` class
2. Add a `Dim(...)` entry to the model's `Dimensions` class, referencing the join
3. Done — the dimension is immediately available in `QuerySpec` and the API

```python
# Example: add customer segment dimension to MRR
class Dimensions:
    ...
    customer_segment = Dim("c.segment", join="customer")
```

No changes to compilation, API, or other metrics needed.
