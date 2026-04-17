"""Retention cube.

- ``RetentionCohortCube`` — cohort membership + monthly activity
"""

from __future__ import annotations

from tidemill.metrics.query import (
    CountDistinct,
    Cube,
    Dim,
    Join,
    TimeDim,
)


class RetentionCohortCube(Cube):
    """Cohort membership and monthly activity for retention analysis."""

    __source__ = "metric_retention_cohort"
    __alias__ = "rc"

    class Joins:
        activity = Join(
            "metric_retention_activity",
            alias="ra",
            on="ra.customer_id = rc.customer_id AND ra.source_id = rc.source_id",
        )
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = rc.source_id AND c.external_id = rc.customer_id",
        )

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
