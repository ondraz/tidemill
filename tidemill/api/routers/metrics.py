"""Generic metric endpoints (list + query-by-body)."""

from __future__ import annotations

import asyncio
import calendar
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter

from tidemill.metrics.base import QuerySpec
from tidemill.metrics.route_helpers import coerce_numerics, query_metric

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def list_metrics() -> list[str]:
    from tidemill.metrics.registry import discover_metrics

    return sorted(m.name for m in discover_metrics())


@router.get("/metrics/summary")
async def get_summary(
    start: date | None = None,
    end: date | None = None,
) -> dict[str, Any]:
    """Return current values for all key metrics in one call.

    The optional ``start``/``end`` window drives the rate-based KPIs
    (churn, NRR, LTV, trial conversion) and the snapshot ``at`` for
    point-in-time KPIs (MRR, ARR, ARPU, active customers). When omitted
    the range defaults to the last full calendar month so the dashboard
    still loads without any parameters.
    """
    from tidemill.api.app import app
    from tidemill.engine import MetricsEngine

    factory = app.state.session_factory

    today = datetime.now(UTC).date()
    if end is None:
        end = today
    if start is None:
        first_of_this_month = end.replace(day=1)
        # first of previous month
        start = (first_of_this_month - timedelta(days=1)).replace(day=1)

    snapshot_at = end
    # LTV and trial conversion are "lifetime" / funnel metrics — a
    # narrow selection (e.g. a single month) often has zero churn or
    # zero trial starts and collapses to null. Use a stable 12-month
    # rolling window anchored at ``end`` so these KPIs stay populated
    # regardless of how narrow the user's main selection is.
    lifetime_start = end - timedelta(days=365)

    # Rate KPIs (logo churn, revenue churn, NRR) need customers active
    # at window start — a wide selection reaching before the first
    # customer collapses the denominator to zero. Measure them over
    # a single calendar month so the cards stay populated whatever
    # range the user picks: if ``end`` is the last day of its month
    # (e.g. the user picked "Last full month"), measure that month;
    # otherwise measure the previous full month.
    last_day = calendar.monthrange(end.year, end.month)[1]
    if end.day == last_day:
        rate_month_start = end.replace(day=1)
        rate_month_end = end
    else:
        rate_month_end = end.replace(day=1) - timedelta(days=1)
        rate_month_start = rate_month_end.replace(day=1)

    queries: dict[str, tuple[str, dict[str, Any]]] = {
        "mrr": ("mrr", {"query_type": "current", "at": snapshot_at}),
        "arr": ("mrr", {"query_type": "arr", "at": snapshot_at}),
        "logo_churn_rate": (
            "churn",
            {"start": rate_month_start, "end": rate_month_end, "type": "logo"},
        ),
        "revenue_churn_rate": (
            "churn",
            {"start": rate_month_start, "end": rate_month_end, "type": "revenue"},
        ),
        "nrr": (
            "retention",
            {"query_type": "nrr", "start": rate_month_start, "end": rate_month_end},
        ),
        "ltv": (
            "ltv",
            {"query_type": "simple", "start": lifetime_start, "end": end},
        ),
        "arpu": ("ltv", {"query_type": "arpu", "at": snapshot_at}),
        "trial_conversion_rate": (
            "trials",
            {"query_type": "conversion_rate", "start": lifetime_start, "end": end},
        ),
        "_breakdown": (
            "mrr",
            {"query_type": "breakdown", "start": lifetime_start, "end": end},
        ),
    }

    async def _run_metric(metric: str, params: dict[str, Any]) -> Any:
        async with factory() as session:
            try:
                return await MetricsEngine(db=session).query(metric, params)
            except Exception:
                return None

    async def _active_customers() -> int | None:
        from tidemill.metrics.mrr.cubes import MRRSnapshotCube

        async with factory() as session:
            try:
                m = MRRSnapshotCube
                q = m.measures.count + m.where("s.mrr_base_cents", ">", 0)
                stmt, params = q.compile(m)
                r = await session.execute(stmt, params)
                row = r.mappings().first()
                return row["subscription_count"] if row else 0
            except Exception:
                return None

    metric_values, active_customers = await asyncio.gather(
        asyncio.gather(*(_run_metric(metric, params) for metric, params in queries.values())),
        _active_customers(),
    )

    result: dict[str, Any] = {}
    for key, val in zip(queries.keys(), metric_values, strict=True):
        if key == "_breakdown":
            continue
        if isinstance(val, dict):
            result.update(val)
        else:
            result[key] = val
    result["active_customers"] = active_customers

    # Quick ratio = (new + expansion + reactivation) / |churn + contraction|.
    # Computed over the 12-month ``lifetime_start``→``end`` window for
    # the same reason LTV/trial conversion do: a narrow selection
    # (e.g. a quiet single month) often has zero losses and collapses
    # the denominator, leaving the KPI blank on the overview.
    breakdown = dict(zip(queries.keys(), metric_values, strict=True))["_breakdown"]
    amounts: dict[str, float] = {}
    if isinstance(breakdown, list):
        for row in breakdown:
            mt = str(row.get("movement_type", "")).lower()
            amounts[mt] = float(row.get("amount_base") or 0)
    gains = amounts.get("new", 0) + amounts.get("expansion", 0) + amounts.get("reactivation", 0)
    losses = abs(amounts.get("churn", 0)) + abs(amounts.get("contraction", 0))
    result["quick_ratio"] = gains / losses if losses > 0 else None

    return coerce_numerics(result)


@router.post("/metrics/{metric}")
async def post_query_metric(
    metric: str,
    body: dict[str, Any],
) -> Any:
    from tidemill.api.schemas import QuerySpecSchema

    params = body.get("params", {})
    raw_spec = body.get("spec")
    spec = None
    if raw_spec:
        s = QuerySpecSchema(**raw_spec)
        spec = QuerySpec(
            dimensions=s.dimensions,
            filters=s.filters,
            granularity=s.granularity,
        )
    return await query_metric(metric, params, spec)
