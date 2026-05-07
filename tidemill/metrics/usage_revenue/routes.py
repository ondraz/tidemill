"""Usage revenue endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends

from tidemill.metrics.base import QuerySpec
from tidemill.metrics.route_helpers import parse_spec, query_metric

router = APIRouter(tags=["metrics"])


@router.get("/metrics/usage-revenue")
async def get_usage_revenue(
    start: date,
    end: date,
    spec: QuerySpec | None = Depends(parse_spec),
) -> Any:
    return await query_metric(
        "usage_revenue",
        {"query_type": "total", "start": start, "end": end},
        spec,
    )


@router.get("/metrics/usage-revenue/series")
async def get_usage_revenue_series(
    start: date,
    end: date,
    interval: str = "month",
    spec: QuerySpec | None = Depends(parse_spec),
) -> Any:
    return await query_metric(
        "usage_revenue",
        {"query_type": "series", "start": start, "end": end, "interval": interval},
        spec,
    )


@router.get("/metrics/usage-revenue/by-customer")
async def get_usage_revenue_by_customer(
    start: date,
    end: date,
    spec: QuerySpec | None = Depends(parse_spec),
) -> Any:
    return await query_metric(
        "usage_revenue",
        {"query_type": "by_customer", "start": start, "end": end},
        spec,
    )
