"""MRR cubes.

- ``MRRSnapshotCube``  — current MRR per subscription
- ``MRRMovementCube``  — append-only log of MRR changes
"""

from __future__ import annotations

from subscriptions.metrics.query import (
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
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = s.source_id AND c.external_id = s.customer_id",
        )

    class Measures:
        mrr = Sum("s.mrr_usd_cents", label="mrr")
        mrr_original = Sum("s.mrr_cents", label="mrr_original")
        count = CountDistinct("s.subscription_id", label="subscription_count")

    class Dimensions:
        source_id = Dim("s.source_id")
        currency = Dim("s.currency")
        plan_id = Dim("sub.plan_id", join="subscription")
        plan_interval = Dim("p.interval", join="plan", label="plan_interval")
        customer_country = Dim("c.country", join="customer", label="customer_country")

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
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = m.source_id AND c.external_id = m.customer_id",
        )

    class Measures:
        amount = Sum("m.amount_usd_cents", label="amount_usd")
        amount_original = Sum("m.amount_cents", label="amount_original")
        count = CountDistinct("m.event_id", label="event_count")

    class Dimensions:
        source_id = Dim("m.source_id")
        currency = Dim("m.currency")
        movement_type = Dim("m.movement_type")
        plan_id = Dim("sub.plan_id", join="subscription")
        plan_interval = Dim("p.interval", join="plan", label="plan_interval")
        customer_country = Dim("c.country", join="customer", label="customer_country")

    class TimeDimensions:
        occurred_at = TimeDim("m.occurred_at")
