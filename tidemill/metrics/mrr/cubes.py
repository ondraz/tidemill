"""MRR cubes.

- ``MRRSnapshotCube``  — current MRR per subscription
- ``MRRMovementCube``  — append-only log of MRR changes
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

    class TimeDimensions:
        occurred_at = TimeDim("m.occurred_at")
