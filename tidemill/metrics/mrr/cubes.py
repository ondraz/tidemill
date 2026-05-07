"""MRR cubes.

- ``MRRSnapshotCube``  — current MRR per subscription
- ``MRRMovementCube``  — append-only log of MRR changes

Computed dimensions (``mrr_band``, ``arr_band``, ``tenure_months``,
``cohort_month``) are expressed as raw SQL in the ``Dim.column`` field —
``literal_column`` handles arbitrary expressions, so the segmentation layer
can filter or group by them exactly like any declared column.
"""

from __future__ import annotations

from tidemill.metrics.query import (
    CountDistinct,
    Cube,
    Dim,
    Join,
    Sum,
    TimeDim,
)

# ── Shared computed-dimension SQL ───────────────────────────────────────
# These expressions assume the customer alias is `c` (every cube with a
# `customer` join uses this alias today).

_TENURE_MONTHS_SQL = (
    "(EXTRACT(YEAR FROM AGE(CURRENT_DATE, c.created_at))::int * 12 "
    "+ EXTRACT(MONTH FROM AGE(CURRENT_DATE, c.created_at))::int)"
)

_COHORT_MONTH_SQL = "DATE_TRUNC('month', c.created_at)::date"


def _mrr_band_sql(mrr_col: str) -> str:
    """Bucket an MRR-in-cents column into labeled bands."""
    return (
        "CASE"
        f" WHEN {mrr_col} <= 0 THEN 'Free'"
        f" WHEN {mrr_col} < 10000 THEN '<$100'"
        f" WHEN {mrr_col} < 50000 THEN '$100-$500'"
        f" WHEN {mrr_col} < 100000 THEN '$500-$1000'"
        f" WHEN {mrr_col} < 500000 THEN '$1000-$5000'"
        " ELSE '$5000+'"
        " END"
    )


def _arr_band_sql(mrr_col: str) -> str:
    """Bucket an annualized MRR column (= ``mrr_col * 12``) into labeled bands."""
    return (
        "CASE"
        f" WHEN {mrr_col} * 12 <= 0 THEN 'Free'"
        f" WHEN {mrr_col} * 12 < 120000 THEN '<$1.2k'"
        f" WHEN {mrr_col} * 12 < 600000 THEN '$1.2k-$6k'"
        f" WHEN {mrr_col} * 12 < 1200000 THEN '$6k-$12k'"
        f" WHEN {mrr_col} * 12 < 6000000 THEN '$12k-$60k'"
        " ELSE '$60k+'"
        " END"
    )


class MRRSnapshotCube(Cube):
    """Current MRR per subscription.  Updated on every subscription event."""

    __source__ = "metric_mrr_snapshot"
    __alias__ = "s"

    class Joins:
        subscription = Join(
            "subscription",
            alias="sub",
            on="sub.source_id = s.source_id AND sub.external_id = s.subscription_id",
        )
        plan = Join(
            "plan",
            alias="p",
            on="p.id = sub.plan_id",
            depends_on=["subscription"],
        )
        product = Join(
            "product",
            alias="prod",
            on="prod.id = p.product_id",
            depends_on=["plan"],
        )
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = s.source_id AND c.external_id = s.customer_id",
        )

    class Measures:
        mrr = Sum("s.mrr_base_cents", label="mrr")
        mrr_original = Sum("s.mrr_cents", label="mrr_original")
        # Component breakdown (subscription_mrr + usage_mrr = mrr).
        subscription_mrr = Sum("s.subscription_mrr_base_cents", label="subscription_mrr")
        subscription_mrr_original = Sum(
            "s.subscription_mrr_cents", label="subscription_mrr_original"
        )
        usage_mrr = Sum("s.usage_mrr_base_cents", label="usage_mrr")
        usage_mrr_original = Sum("s.usage_mrr_cents", label="usage_mrr_original")
        count = CountDistinct("s.subscription_id", label="subscription_count")
        customer_count = CountDistinct("s.customer_id", label="customer_count")

    class Dimensions:
        # Source
        source_id = Dim("s.source_id")
        currency = Dim("s.currency")
        # Plan (via subscription → plan)
        plan_id = Dim("sub.plan_id", join="subscription")
        plan_name = Dim("p.name", join="plan", label="plan_name")
        plan_interval = Dim("p.interval", join="plan", label="plan_interval")
        billing_scheme = Dim("p.billing_scheme", join="plan", label="billing_scheme")
        usage_type = Dim("p.usage_type", join="plan", label="usage_type")
        # Product (via subscription → plan → product)
        product_name = Dim("prod.name", join="product", label="product_name")
        # Customer
        customer_name = Dim("c.name", join="customer", label="customer_name")
        customer_country = Dim("c.country", join="customer", label="customer_country")
        # Subscription attributes
        collection_method = Dim(
            "sub.collection_method", join="subscription", label="collection_method"
        )
        cancel_at_period_end = Dim(
            "sub.cancel_at_period_end", join="subscription", label="cancel_at_period_end"
        )
        # Computed — buckets and customer-tenure derived from c.created_at.
        mrr_band = Dim(_mrr_band_sql("s.mrr_base_cents"), join="customer", label="MRR band")
        arr_band = Dim(_arr_band_sql("s.mrr_base_cents"), join="customer", label="ARR band")
        tenure_months = Dim(_TENURE_MONTHS_SQL, join="customer", label="Tenure (months)")
        cohort_month = Dim(_COHORT_MONTH_SQL, join="customer", label="Cohort month")

    class TimeDimensions:
        snapshot_at = TimeDim("s.snapshot_at")


class MRRMovementCube(Cube):
    """Append-only log of MRR changes.  Used for breakdown and time-series."""

    __source__ = "metric_mrr_movement"
    __alias__ = "m"

    class Joins:
        subscription = Join(
            "subscription",
            alias="sub",
            on="sub.source_id = m.source_id AND sub.external_id = m.subscription_id",
        )
        plan = Join(
            "plan",
            alias="p",
            on="p.id = sub.plan_id",
            depends_on=["subscription"],
        )
        product = Join(
            "product",
            alias="prod",
            on="prod.id = p.product_id",
            depends_on=["plan"],
        )
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = m.source_id AND c.external_id = m.customer_id",
        )

    class Measures:
        amount = Sum("m.amount_base_cents", label="amount_base")
        amount_original = Sum("m.amount_cents", label="amount_original")
        count = CountDistinct("m.event_id", label="event_count")

    class Dimensions:
        # Source
        source_id = Dim("m.source_id")
        customer_id = Dim("m.customer_id")
        currency = Dim("m.currency")
        movement_type = Dim("m.movement_type")
        # Origin: 'subscription' (licensed plan changes/lifecycle) or
        # 'usage' (trailing-3m component shifts). Lets the waterfall
        # split expansion/contraction by source.
        movement_source = Dim("m.source", label="movement_source")
        # Plan
        plan_id = Dim("sub.plan_id", join="subscription")
        plan_name = Dim("p.name", join="plan", label="plan_name")
        plan_interval = Dim("p.interval", join="plan", label="plan_interval")
        billing_scheme = Dim("p.billing_scheme", join="plan", label="billing_scheme")
        usage_type = Dim("p.usage_type", join="plan", label="usage_type")
        # Product
        product_name = Dim("prod.name", join="product", label="product_name")
        # Customer
        customer_name = Dim("c.name", join="customer", label="customer_name")
        customer_country = Dim("c.country", join="customer", label="customer_country")
        # Subscription attributes
        collection_method = Dim(
            "sub.collection_method", join="subscription", label="collection_method"
        )
        # Computed
        tenure_months = Dim(_TENURE_MONTHS_SQL, join="customer", label="Tenure (months)")
        cohort_month = Dim(_COHORT_MONTH_SQL, join="customer", label="Cohort month")

    class TimeDimensions:
        occurred_at = TimeDim("m.occurred_at")
