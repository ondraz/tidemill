"""ExpensesMetric — total expense by period, account type, or vendor.

Reads directly from ``bill`` / ``bill_line`` / ``expense`` / ``expense_line``
joined to ``account`` (chart of accounts) and ``vendor``. Sums in base
currency (``*_base_cents``) so multi-currency sources combine correctly.

The unit of analysis is the *line item*, not the bill header — this lets
callers slice expenses by account type (e.g., separate Hosting from
Salaries when both appear on a single bill). Voided bills/expenses are
excluded.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from tidemill.metrics.base import Metric, QuerySpec
from tidemill.metrics.registry import register

if TYPE_CHECKING:
    from datetime import date

    from fastapi import APIRouter


def _start_of_day(d: date | None) -> datetime | None:
    """Coerce a bare ``date`` to its UTC midnight timestamp.

    The ``txn_date`` column is ``TIMESTAMPTZ``; comparing it directly to a
    ``date`` in PostgreSQL silently casts the date to midnight, which would
    drop any rows occurring later that same day. We coerce the bound to a
    full timestamp here so the documented inclusive ``[start, end]`` window
    holds regardless of time-of-day. (Matches ``cubes.py`` for cube metrics.)
    """
    if d is None:
        return None
    return datetime.combine(d, time.min, tzinfo=UTC)


def _end_of_day(d: date | None) -> datetime | None:
    """Coerce a bare ``date`` to its UTC end-of-day (``23:59:59.999999``)."""
    if d is None:
        return None
    return datetime.combine(d, time.max, tzinfo=UTC)


# Lines from both bills and direct expenses, with the parent header's
# txn_date and currency carried through. ``status`` is borrowed from the
# bill header — direct expenses are 'paid' by definition (cash/credit
# already moved). Voided bills/expenses are filtered out.
_EXPENSE_LINES_CTE = """
WITH expense_lines AS (
    SELECT b.source_id,
           b.txn_date,
           b.vendor_id,
           bl.account_id,
           bl.amount_cents,
           bl.amount_base_cents,
           bl.currency,
           b.status AS bill_status,
           'bill'   AS source_kind
    FROM bill_line bl
    JOIN bill b ON b.id = bl.bill_id
    WHERE b.voided_at IS NULL
    UNION ALL
    SELECT e.source_id,
           e.txn_date,
           e.vendor_id,
           el.account_id,
           el.amount_cents,
           el.amount_base_cents,
           el.currency,
           'paid' AS bill_status,
           'expense' AS source_kind
    FROM expense_line el
    JOIN expense e ON e.id = el.expense_id
    WHERE e.voided_at IS NULL
)
"""


@register
class ExpensesMetric(Metric):
    name = "expenses"

    @property
    def router(self) -> APIRouter:
        from tidemill.metrics.expenses.routes import router

        return router

    async def query(self, params: dict[str, Any], spec: QuerySpec | None = None) -> Any:
        match params.get("query_type"):
            case "total":
                return await self._total(params.get("start"), params.get("end"))
            case "by_account_type":
                return await self._by_account_type(params["start"], params["end"])
            case "by_vendor":
                return await self._by_vendor(params["start"], params["end"])
            case "series":
                return await self._series(
                    params["start"],
                    params["end"],
                    params.get("interval", "month"),
                )
            case other:
                raise ValueError(f"Unknown query_type: {other}")

    async def _total(self, start: date | None, end: date | None) -> dict[str, Any]:
        """Total expense (in base cents) over [start, end] — both inclusive."""
        params: dict[str, Any] = {}
        where = []
        if start is not None:
            where.append("el.txn_date >= :start")
            params["start"] = _start_of_day(start)
        if end is not None:
            where.append("el.txn_date <= :end")
            params["end"] = _end_of_day(end)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        sql = (
            _EXPENSE_LINES_CTE
            + " SELECT COALESCE(SUM(el.amount_base_cents), 0) AS total_base_cents,"
            "        COUNT(*) AS line_count"
            " FROM expense_lines el" + clause
        )
        result = await self.db.execute(text(sql), params)
        row = result.mappings().one()
        return {
            "total_base_cents": int(row["total_base_cents"] or 0),
            "line_count": int(row["line_count"] or 0),
        }

    async def _by_account_type(self, start: date, end: date) -> list[dict[str, Any]]:
        sql = (
            _EXPENSE_LINES_CTE + " SELECT COALESCE(a.account_type, 'unknown') AS account_type,"
            "        SUM(el.amount_base_cents) AS amount_base_cents,"
            "        COUNT(*) AS line_count"
            " FROM expense_lines el"
            " LEFT JOIN account a ON a.id = el.account_id"
            " WHERE el.txn_date BETWEEN :start AND :end"
            " GROUP BY 1"
            " ORDER BY amount_base_cents DESC"
        )
        result = await self.db.execute(
            text(sql),
            {"start": _start_of_day(start), "end": _end_of_day(end)},
        )
        return [
            {
                "account_type": r["account_type"],
                "amount_base_cents": int(r["amount_base_cents"] or 0),
                "line_count": int(r["line_count"] or 0),
            }
            for r in result.mappings().all()
        ]

    async def _by_vendor(self, start: date, end: date) -> list[dict[str, Any]]:
        sql = (
            _EXPENSE_LINES_CTE + " SELECT v.id AS vendor_id,"
            "        v.name AS vendor_name,"
            "        SUM(el.amount_base_cents) AS amount_base_cents,"
            "        COUNT(*) AS line_count"
            " FROM expense_lines el"
            " LEFT JOIN vendor v ON v.id = el.vendor_id"
            " WHERE el.txn_date BETWEEN :start AND :end"
            " GROUP BY 1, 2"
            " ORDER BY amount_base_cents DESC"
        )
        result = await self.db.execute(
            text(sql),
            {"start": _start_of_day(start), "end": _end_of_day(end)},
        )
        return [
            {
                "vendor_id": r["vendor_id"],
                "vendor_name": r["vendor_name"] or "(unassigned)",
                "amount_base_cents": int(r["amount_base_cents"] or 0),
                "line_count": int(r["line_count"] or 0),
            }
            for r in result.mappings().all()
        ]

    async def _series(self, start: date, end: date, interval: str) -> list[dict[str, Any]]:
        # Mirrors MRR/retention DATE_TRUNC convention so client-side period
        # keys line up across metrics.
        if interval not in ("day", "week", "month", "quarter", "year"):
            raise ValueError(f"Unsupported interval: {interval}")
        sql = (
            _EXPENSE_LINES_CTE + f" SELECT DATE_TRUNC('{interval}', el.txn_date)::date AS period,"
            "        COALESCE(a.account_type, 'unknown') AS account_type,"
            "        SUM(el.amount_base_cents) AS amount_base_cents"
            " FROM expense_lines el"
            " LEFT JOIN account a ON a.id = el.account_id"
            " WHERE el.txn_date BETWEEN :start AND :end"
            " GROUP BY 1, 2"
            " ORDER BY 1, 2"
        )
        result = await self.db.execute(
            text(sql),
            {"start": _start_of_day(start), "end": _end_of_day(end)},
        )
        return [
            {
                "period": r["period"].isoformat() if r["period"] else None,
                "account_type": r["account_type"],
                "amount_base_cents": int(r["amount_base_cents"] or 0),
            }
            for r in result.mappings().all()
        ]
