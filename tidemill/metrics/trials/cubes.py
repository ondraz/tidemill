"""Trials cube.

- ``TrialCube`` — one row per trial (per subscription that entered
  trialing).  Queries are **cohort-based**: a trial belongs to the period
  of its ``started_at``, and its ``converted_at`` / ``expired_at`` outcome
  is attributed to that same cohort regardless of when it happens.
"""

from __future__ import annotations

from tidemill.metrics.mrr.cubes import _TENURE_MONTHS_SQL, SOURCE_DIM, source_join
from tidemill.metrics.query import (
    Count,
    CountDistinct,
    Cube,
    Dim,
    Join,
    TimeDim,
)


class TrialCube(Cube):
    """Per-trial outcomes.  Cohort = month of ``started_at``."""

    __source__ = "metric_trial"
    __alias__ = "t"

    class Joins:
        connector_source = source_join("t")
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = t.source_id AND c.external_id = t.customer_id",
        )

    class Measures:
        # count(*) counts all rows; count(col) counts non-null values.
        # Every row has started_at, so started_count == count(*).
        started_count = Count("*", label="started")
        converted_count = Count("t.converted_at", label="converted")
        expired_count = Count("t.expired_at", label="expired")
        customer_count = CountDistinct("t.customer_id", label="customer_count")

    class Dimensions:
        source_id = Dim("t.source_id")
        source = SOURCE_DIM
        customer_country = Dim("c.country", join="customer", label="customer_country")
        # Computed
        tenure_months = Dim(_TENURE_MONTHS_SQL, join="customer", label="Tenure (months)")

    class TimeDimensions:
        started_at = TimeDim("t.started_at")
        converted_at = TimeDim("t.converted_at")
        expired_at = TimeDim("t.expired_at")
