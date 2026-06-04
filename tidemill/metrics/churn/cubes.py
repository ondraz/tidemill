"""Churn cubes.

- ``ChurnCustomerStateCube`` — tracks active/churned state per customer
- ``ChurnEventCube``         — individual churn events for rate calculation
"""

from __future__ import annotations

from tidemill.metrics.mrr.cubes import (
    _COHORT_MONTH_SQL,
    _TENURE_MONTHS_SQL,
    SOURCE_DIM,
    source_join,
)
from tidemill.metrics.query import (
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
        connector_source = source_join("cs")
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = cs.source_id AND c.external_id = cs.customer_id",
        )

    class Measures:
        count = CountDistinct("cs.customer_id", label="customer_count")

    class Dimensions:
        source_id = Dim("cs.source_id")
        source = SOURCE_DIM
        customer_id = Dim("cs.customer_id")
        customer_name = Dim("c.name", join="customer", label="customer_name")
        customer_country = Dim("c.country", join="customer", label="customer_country")
        # Computed
        tenure_months = Dim(_TENURE_MONTHS_SQL, join="customer", label="Tenure (months)")
        cohort_month = Dim(_COHORT_MONTH_SQL, join="customer", label="Cohort month")

    class TimeDimensions:
        first_active_at = TimeDim("cs.first_active_at")
        churned_at = TimeDim("cs.churned_at")


class ChurnEventCube(Cube):
    """Individual churn events for rate calculation."""

    __source__ = "metric_churn_event"
    __alias__ = "ce"

    class Joins:
        connector_source = source_join("ce")
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = ce.source_id AND c.external_id = ce.customer_id",
        )
        customer_state = Join(
            "metric_churn_customer_state",
            alias="cs",
            on="cs.source_id = ce.source_id AND cs.customer_id = ce.customer_id",
        )

    class Measures:
        count = Count("*", label="churn_count")
        revenue_lost = Sum("ce.mrr_cents", label="revenue_lost")

    class Dimensions:
        source_id = Dim("ce.source_id")
        source = SOURCE_DIM
        customer_id = Dim("ce.customer_id")
        churn_type = Dim("ce.churn_type")
        cancel_reason = Dim("ce.cancel_reason")
        customer_name = Dim("c.name", join="customer", label="customer_name")
        customer_country = Dim("c.country", join="customer", label="customer_country")
        # Used to scope churn events to customers active at period start
        customer_first_active = Dim(
            "cs.first_active_at", join="customer_state", label="customer_first_active"
        )
        # Computed
        tenure_months = Dim(_TENURE_MONTHS_SQL, join="customer", label="Tenure (months)")
        cohort_month = Dim(_COHORT_MONTH_SQL, join="customer", label="Cohort month")

    class TimeDimensions:
        occurred_at = TimeDim("ce.occurred_at")
