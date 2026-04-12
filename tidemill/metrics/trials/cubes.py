"""Trials cube.

- ``TrialEventCube`` — trial lifecycle events for conversion rate analysis
"""

from __future__ import annotations

from tidemill.metrics.query import (
    Count,
    CountDistinct,
    Cube,
    Dim,
    Join,
    TimeDim,
)


class TrialEventCube(Cube):
    """Append-only log of trial events.  Used for conversion rate queries."""

    __source__ = "metric_trial_event"
    __alias__ = "te"

    class Joins:
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = te.source_id AND c.external_id = te.customer_id",
        )

    class Measures:
        count = Count("*", label="trial_count")
        customer_count = CountDistinct("te.customer_id", label="customer_count")

    class Dimensions:
        source_id = Dim("te.source_id")
        event_type = Dim("te.event_type")
        customer_country = Dim("c.country", join="customer", label="customer_country")

    class TimeDimensions:
        occurred_at = TimeDim("te.occurred_at")
