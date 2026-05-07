"""Usage revenue cube.

``UsageRevenueCube`` reads ``metric_mrr_usage_component`` — the canonical
per-(subscription, month) bucket of finalized metered charges populated by
:mod:`tidemill.metrics.mrr.usage`. Usage revenue is an actuals view over the
same data the MRR trailing-3m component is computed from; nothing is
re-ingested.
"""

from __future__ import annotations

from tidemill.metrics.mrr.cubes import _COHORT_MONTH_SQL, _TENURE_MONTHS_SQL
from tidemill.metrics.query import (
    CountDistinct,
    Cube,
    Dim,
    Join,
    Sum,
    TimeDim,
)


class UsageRevenueCube(Cube):
    """Per-subscription monthly usage charges (actuals)."""

    __source__ = "metric_mrr_usage_component"
    __alias__ = "u"

    class Joins:
        subscription = Join(
            "subscription",
            alias="sub",
            on="sub.source_id = u.source_id AND sub.external_id = u.subscription_id",
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
            on="c.source_id = u.source_id AND c.external_id = u.customer_id",
        )

    class Measures:
        revenue = Sum("u.usage_base_cents", label="revenue")
        revenue_original = Sum("u.usage_cents", label="revenue_original")
        subscription_count = CountDistinct("u.subscription_id", label="subscription_count")
        customer_count = CountDistinct("u.customer_id", label="customer_count")

    class Dimensions:
        source_id = Dim("u.source_id")
        customer_id = Dim("u.customer_id")
        subscription_id = Dim("u.subscription_id")
        currency = Dim("u.currency")
        plan_id = Dim("sub.plan_id", join="subscription")
        plan_name = Dim("p.name", join="plan", label="plan_name")
        plan_interval = Dim("p.interval", join="plan", label="plan_interval")
        product_name = Dim("prod.name", join="product", label="product_name")
        customer_name = Dim("c.name", join="customer", label="customer_name")
        customer_country = Dim("c.country", join="customer", label="customer_country")
        tenure_months = Dim(_TENURE_MONTHS_SQL, join="customer", label="Tenure (months)")
        cohort_month = Dim(_COHORT_MONTH_SQL, join="customer", label="Cohort month")

    class TimeDimensions:
        period_start = TimeDim("u.period_start")
