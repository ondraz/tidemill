"""Expenses metric endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter

from tidemill.metrics.route_helpers import query_metric

router = APIRouter(tags=["metrics"])


@router.get("/metrics/expenses")
async def get_expenses_total(
    start: date | None = None, end: date | None = None
) -> Any:
    return await query_metric(
        "expenses",
        {"query_type": "total", "start": start, "end": end},
        spec=None,
    )


@router.get("/metrics/expenses/by_account_type")
async def get_expenses_by_account_type(start: date, end: date) -> Any:
    return await query_metric(
        "expenses",
        {"query_type": "by_account_type", "start": start, "end": end},
        spec=None,
    )


@router.get("/metrics/expenses/by_vendor")
async def get_expenses_by_vendor(start: date, end: date) -> Any:
    return await query_metric(
        "expenses",
        {"query_type": "by_vendor", "start": start, "end": end},
        spec=None,
    )


@router.get("/metrics/expenses/series")
async def get_expenses_series(
    start: date, end: date, interval: str = "month"
) -> Any:
    return await query_metric(
        "expenses",
        {
            "query_type": "series",
            "start": start,
            "end": end,
            "interval": interval,
        },
        spec=None,
    )
