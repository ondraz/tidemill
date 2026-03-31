"""Churn cubes.

- ``ChurnCustomerStateCube`` — tracks active/churned state per customer
- ``ChurnEventCube``         — individual churn events for rate calculation
"""

from __future__ import annotations

from subscriptions.metrics.query import (
    Count,
    CountDistinct,
    Cube,
    Dim,
    Join,
    Sum,
    TimeDim,
)


class ChurnCustomerStateCube(Cube):
    """Active/churned state per customer.  Updated by subscription events."""

    __source__ = "metric_churn_customer_state"
    __alias__ = "cs"

    class Joins:
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = cs.source_id AND c.external_id = cs.customer_id",
        )

    class Measures:
        count = CountDistinct("cs.customer_id", label="customer_count")

    class Dimensions:
        source_id = Dim("cs.source_id")
        customer_country = Dim("c.country", join="customer", label="customer_country")

    class TimeDimensions:
        first_active_at = TimeDim("cs.first_active_at")
        churned_at = TimeDim("cs.churned_at")


class ChurnEventCube(Cube):
    """Individual churn events for rate calculation."""

    __source__ = "metric_churn_event"
    __alias__ = "ce"

    class Joins:
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = ce.source_id AND c.external_id = ce.customer_id",
        )

    class Measures:
        count = Count("*", label="churn_count")
        revenue_lost = Sum("ce.mrr_cents", label="revenue_lost")

    class Dimensions:
        source_id = Dim("ce.source_id")
        churn_type = Dim("ce.churn_type")
        customer_country = Dim("c.country", join="customer", label="customer_country")

    class TimeDimensions:
        occurred_at = TimeDim("ce.occurred_at")
