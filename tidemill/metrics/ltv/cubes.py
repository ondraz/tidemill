"""LTV cubes.

- ``LtvInvoiceCube`` — paid invoices for cohort LTV and revenue tracking
"""

from __future__ import annotations

from tidemill.metrics.query import (
    Count,
    CountDistinct,
    Cube,
    Dim,
    Join,
    Sum,
    TimeDim,
)


class LtvInvoiceCube(Cube):
    """Append-only log of paid invoices.  Used for cohort LTV."""

    __source__ = "metric_ltv_invoice"
    __alias__ = "li"

    class Joins:
        customer = Join(
            "customer",
            alias="c",
            on="c.source_id = li.source_id AND c.external_id = li.customer_id",
        )
        cohort = Join(
            "metric_retention_cohort",
            alias="rc",
            on="rc.source_id = li.source_id AND rc.customer_id = li.customer_id",
        )

    class Measures:
        total_revenue = Sum("li.amount_base_cents", label="total_revenue")
        total_revenue_original = Sum("li.amount_cents", label="total_revenue_original")
        invoice_count = Count("*", label="invoice_count")
        customer_count = CountDistinct("li.customer_id", label="customer_count")

    class Dimensions:
        source_id = Dim("li.source_id")
        currency = Dim("li.currency")
        customer_country = Dim("c.country", join="customer", label="customer_country")
        cohort_month = Dim("rc.cohort_month", join="cohort", label="cohort_month")

    class TimeDimensions:
        paid_at = TimeDim("li.paid_at")
