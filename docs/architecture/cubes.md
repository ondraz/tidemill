# Cubes & Query Algebra

> Declarative query building: cubes define what's queryable, algebraic fragments compose queries.
> Last updated: March 2026

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
        subscription = Join(
            "subscription AS sub",
            on="sub.source_id = s.source_id AND sub.external_id = s.subscription_id",
        )
        plan = Join(
            "plan AS p",
            on="p.id = sub.plan_id",
            depends_on=["subscription"],
        )
        customer = Join(
            "customer AS c",
            on="c.source_id = s.source_id AND c.external_id = s.customer_id",
        )

    class Measures:
        mrr = Sum("s.mrr_base_cents")
        mrr_original = Sum("s.mrr_cents")       # in original currency
        count = CountDistinct("s.subscription_id")

    class Dimensions:
        source_id = Dim("s.source_id")
        currency = Dim("s.currency")
        plan_id = Dim("sub.plan_id", join="subscription")
        plan_interval = Dim("p.interval", join="plan")
        customer_country = Dim("c.country", join="customer")

    class TimeDimensions:
        snapshot_at = TimeDim("s.snapshot_at")
```

Key properties:

- **Join dependencies** — `plan` depends on `subscription`. Requesting `plan_interval` automatically pulls in both joins in the correct order.
- **Lazy joins** — only dimensions/filters that are actually used trigger their joins. A query with no plan dimensions never joins the `plan` table.
- **Introspection** — the model can list its available dimensions and measures at runtime, enabling API validation and documentation generation.

```python
MRRSnapshotCube.available_dimensions()
# ['source_id', 'currency', 'plan_id', 'plan_interval', 'customer_country']

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
    extra_group_by: tuple[str, ...] = ()        # non-dimension GROUP BY
    order_by: tuple[str, ...] = ()

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
            extra_group_by=self.extra_group_by + other.extra_group_by,
            order_by=self.order_by + other.order_by,
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
3. **Add measures** — aggregation expressions in SELECT (`SUM(...)`, `COUNT(DISTINCT ...)`)
4. **Add dimensions** — column expressions in SELECT and GROUP BY
5. **Add time grain** — `DATE_TRUNC(granularity, column) AS period` in SELECT and GROUP BY
6. **Add filters** — WHERE clauses with bound parameters
7. **Add ORDER BY** — if specified

```python
def compile(self, model: type[Cube]) -> tuple[Select, dict[str, Any]]:
    """Resolve the fragment against its model and emit SQLAlchemy Select + params."""
    source_table = table(self.source).alias(self.alias)
    stmt = select().select_from(source_table)
    params = {}

    # 1. Resolve and add joins in dependency order
    for join_name in _topological_sort(self.joins, model.Joins):
        join_def = getattr(model.Joins, join_name)
        target, on_clause = join_def.to_sqlalchemy()
        stmt = stmt.join(target, on_clause)

    # 2. Add measures
    for m in self.measures:
        stmt = stmt.add_columns(m.to_sqlalchemy())

    # 3. Add dimensions (SELECT + GROUP BY)
    for d in self.dimensions:
        col = d.to_sqlalchemy()
        stmt = stmt.add_columns(col).group_by(col)

    # 4. Add time grain
    if self.time_grain:
        trunc = func.date_trunc(
            self.time_grain.granularity,
            literal_column(self.time_grain.column),
        ).label("period")
        stmt = stmt.add_columns(trunc).group_by(trunc)

    # 5. Add filters
    for f in self.filters:
        clause, f_params = f.to_sqlalchemy()
        stmt = stmt.where(clause)
        params.update(f_params)

    return stmt, params
```

## Concrete Cubes

These are the cubes for the project's [metric tables](database.md#metric-tables). Each maps a fact table to its available joins, measures, and dimensions.

### MRR Snapshot Cube

```python
class MRRSnapshotCube(Cube):
    """Current MRR per subscription. Updated on every subscription event."""
    __source__ = "metric_mrr_snapshot"
    __alias__ = "s"

    class Joins:
        subscription = Join(
            "subscription AS sub",
            on="sub.source_id = s.source_id AND sub.external_id = s.subscription_id",
        )
        plan = Join(
            "plan AS p",
            on="p.id = sub.plan_id",
            depends_on=["subscription"],
        )
        customer = Join(
            "customer AS c",
            on="c.source_id = s.source_id AND c.external_id = s.customer_id",
        )

    class Measures:
        mrr = Sum("s.mrr_base_cents", label="mrr")
        mrr_original = Sum("s.mrr_cents", label="mrr_original")
        count = CountDistinct("s.subscription_id", label="subscription_count")

    class Dimensions:
        source_id = Dim("s.source_id")
        currency = Dim("s.currency")
        plan_id = Dim("sub.plan_id", join="subscription")
        plan_interval = Dim("p.interval", join="plan")
        customer_country = Dim("c.country", join="customer")

    class TimeDimensions:
        snapshot_at = TimeDim("s.snapshot_at")
```

### MRR Movement Cube

```python
class MRRMovementCube(Cube):
    """Append-only log of MRR changes. Used for breakdown and time-series queries."""
    __source__ = "metric_mrr_movement"
    __alias__ = "m"

    class Joins:
        subscription = Join(
            "subscription AS sub",
            on="sub.source_id = m.source_id AND sub.external_id = m.subscription_id",
        )
        plan = Join(
            "plan AS p",
            on="p.id = sub.plan_id",
            depends_on=["subscription"],
        )
        customer = Join(
            "customer AS c",
            on="c.source_id = m.source_id AND c.external_id = m.customer_id",
        )

    class Measures:
        amount = Sum("m.amount_base_cents", label="amount_base")
        amount_original = Sum("m.amount_cents", label="amount_original")
        count = CountDistinct("m.event_id", label="event_count")

    class Dimensions:
        source_id = Dim("m.source_id")
        currency = Dim("m.currency")
        movement_type = Dim("m.movement_type")
        plan_id = Dim("sub.plan_id", join="subscription")
        plan_interval = Dim("p.interval", join="plan")
        customer_country = Dim("c.country", join="customer")

    class TimeDimensions:
        occurred_at = TimeDim("m.occurred_at")
```

### Churn Event Cube

```python
class ChurnEventCube(Cube):
    """Churn events for rate calculation. No subscription_id — joins via customer only."""
    __source__ = "metric_churn_event"
    __alias__ = "ce"

    class Joins:
        customer = Join(
            "customer AS c",
            on="c.source_id = ce.source_id AND c.external_id = ce.customer_id",
        )

    class Measures:
        count = Count("*", label="churn_count")
        revenue_lost = Sum("ce.mrr_cents", label="revenue_lost")

    class Dimensions:
        source_id = Dim("ce.source_id")
        churn_type = Dim("ce.churn_type")
        customer_country = Dim("c.country", join="customer")

    class TimeDimensions:
        occurred_at = TimeDim("ce.occurred_at")
```

### Retention Cohort Cube

```python
class RetentionCohortCube(Cube):
    """Cohort membership and monthly activity for retention analysis."""
    __source__ = "metric_retention_cohort"
    __alias__ = "rc"

    class Joins:
        activity = Join(
            "metric_retention_activity AS ra",
            on="ra.customer_id = rc.customer_id AND ra.source_id = rc.source_id",
        )
        customer = Join(
            "customer AS c",
            on="c.source_id = rc.source_id AND c.external_id = rc.customer_id",
        )

    class Measures:
        cohort_size = CountDistinct("rc.customer_id", label="cohort_size")
        active_count = CountDistinct("ra.customer_id", label="active_count")

    class Dimensions:
        source_id = Dim("rc.source_id")
        cohort_month = Dim("rc.cohort_month")
        active_month = Dim("ra.active_month", join="activity")
        customer_country = Dim("c.country", join="customer")

    class TimeDimensions:
        cohort_month_time = TimeDim("rc.cohort_month")
```

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

    def validate_against(self, model: type[Cube]) -> None:
        """Validate that all referenced dimensions exist in the model. Raises ValueError."""
        available = model.available_dimensions()
        for d in self.dimensions:
            if d not in available:
                raise ValueError(
                    f"Unknown dimension '{d}'. Available: {sorted(available)}"
                )
        for f in self.filters:
            if f not in available:
                raise ValueError(
                    f"Cannot filter on unknown dimension '{f}'. "
                    f"Available: {sorted(available)}"
                )
```

The model's `apply_spec()` method translates a `QuerySpec` into a composed fragment:

```python
@classmethod
def apply_spec(cls, spec: QuerySpec | None) -> QueryFragment:
    """Translate a QuerySpec into a composed QueryFragment."""
    if not spec:
        return QueryFragment()

    spec.validate_against(cls)
    result = QueryFragment()

    for dim_name in spec.dimensions:
        result = result + cls.dimension(dim_name)

    for field_name, value in spec.filters.items():
        if isinstance(value, dict):
            op = next(iter(value))
            result = result + cls.filter(field_name, op, value[op])
        else:
            result = result + cls.filter(field_name, "=", value)

    if spec.granularity:
        time_dims = cls.available_time_dimensions()
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

### No spec — plain aggregate

```python
q = model.measures.mrr + model.where("s.mrr_base_cents", ">", 0)
```

```sql
SELECT SUM(s.mrr_base_cents) / 100.0 AS mrr
FROM metric_mrr_snapshot s
WHERE s.mrr_base_cents > 0
```

### Filter only (no dimensions)

```python
q = model.measures.mrr + model.where("s.mrr_base_cents", ">", 0) + model.filter("plan_interval", "=", "yearly")
```

```sql
SELECT SUM(s.mrr_base_cents) / 100.0 AS mrr
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
       SUM(s.mrr_base_cents) / 100.0 AS mrr
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
       SUM(s.mrr_base_cents) / 100.0 AS mrr
FROM metric_mrr_snapshot s
  JOIN subscription sub ON sub.source_id = s.source_id
                       AND sub.external_id = s.subscription_id
  JOIN customer c ON c.source_id = s.source_id
                 AND c.external_id = s.customer_id
WHERE s.mrr_base_cents > 0
  AND c.country = ANY(:customer_country)
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
       SUM(m.amount_base_cents) / 100.0 AS amount_base
FROM metric_mrr_movement m
  JOIN subscription sub ON sub.source_id = m.source_id
                       AND sub.external_id = m.subscription_id
WHERE m.occurred_at BETWEEN :start AND :end
GROUP BY m.movement_type, sub.plan_id
```

## Implementation Notes

### File Location

The cube machinery lives in `subscriptions/metrics/query.py` — the same file that metrics import from. The concrete cubes are defined alongside their metrics (e.g., `MRRSnapshotCube` in `subscriptions/metrics/mrr/cubes.py`).

### Package Structure

```
subscriptions/metrics/
├── __init__.py          # Metric base class + registry + QuerySpec
├── query.py             # Cube, QueryFragment, compilation
├── mrr/                 # MRRSnapshotCube, MRRMovementCube, MrrMetric
├── churn/               # ChurnEventCube, ChurnMetric
├── retention/           # RetentionCohortCube, RetentionMetric
├── ltv.py               # LTV cubes + metric
└── trials.py            # Trial cubes + metric
```

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
