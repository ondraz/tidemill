"""LtvMetric — query methods and event handler."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from tidemill.metrics.base import Metric, QuerySpec
from tidemill.metrics.ltv.cubes import LtvInvoiceCube
from tidemill.metrics.registry import register

if TYPE_CHECKING:
    from datetime import date

    from fastapi import APIRouter

    from tidemill.events import Event


@register
class LtvMetric(Metric):
    name = "ltv"
    model = LtvInvoiceCube

    @property
    def router(self) -> APIRouter:
        from tidemill.metrics.ltv.routes import router

        return router

    @property
    def dependencies(self) -> list[str]:
        return ["mrr", "churn"]

    @property
    def event_types(self) -> list[str]:
        return ["invoice.paid"]

    async def handle_event(self, event: Event) -> None:
        from tidemill.fx import to_base_cents

        p = event.payload
        amount = p.get("amount_cents", 0)
        currency = p.get("currency", "USD") or "USD"
        amount_base = await to_base_cents(amount, currency, event.occurred_at.date(), self.db)

        await self.db.execute(
            text(
                "INSERT INTO metric_ltv_invoice"
                " (id, event_id, source_id, customer_id,"
                "  amount_cents, amount_base_cents, currency, paid_at)"
                " VALUES (:id, :eid, :src, :cid, :amt, :amtb, :cur, :at)"
                " ON CONFLICT (event_id) DO NOTHING"
            ),
            {
                "id": str(uuid.uuid4()),
                "eid": event.id,
                "src": event.source_id,
                "cid": event.customer_id,
                "amt": amount,
                "amtb": amount_base,
                "cur": currency,
                "at": event.occurred_at,
            },
        )

    async def query(self, params: dict[str, Any], spec: QuerySpec | None = None) -> Any:
        match params.get("query_type"):
            case "simple":
                return await self._simple_ltv(
                    params.get("at"),
                    params["start"],
                    params["end"],
                    spec,
                )
            case "arpu":
                return await self._arpu(params.get("at"), spec)
            case "cohort":
                return await self._cohort_ltv(params["start"], params["end"], spec)
            case other:
                raise ValueError(f"Unknown query_type: {other}")

    async def _arpu(
        self,
        at: date | None,
        spec: QuerySpec | None,
    ) -> float | None:
        """Average Revenue Per User = total active MRR / distinct active customers.

        When ``at`` is provided, the calculation is historical: the active
        set is every customer whose cumulative MRR movements before ``at``
        sum to a positive value, matching the ``[month-start, next-month-start)``
        cohort semantics used by MRR.  When ``at`` is ``None``, the snapshot
        table is used for an efficient current-state read.
        """
        if at is not None:
            return await self._historical_arpu(at, spec)

        from tidemill.metrics.mrr.cubes import MRRSnapshotCube

        sm = MRRSnapshotCube
        q = sm.measures.mrr + sm.measures.customer_count + sm.where("s.mrr_base_cents", ">", 0)
        if spec:
            q = q + sm.apply_spec(spec)

        stmt, params = q.compile(sm)
        result = await self.db.execute(stmt, params)
        row = result.mappings().first()
        if not row or not row["customer_count"]:
            return None
        return float(row["mrr"] / row["customer_count"])

    async def _historical_arpu(
        self,
        at: date,
        spec: QuerySpec | None,
    ) -> float | None:
        from tidemill.metrics.mrr.cubes import MRRMovementCube

        mm = MRRMovementCube
        q = mm.measures.amount + mm.dimension("customer_id") + mm.filter("occurred_at", "<", at)
        if spec:
            q = q + mm.apply_spec(spec)

        stmt, params = q.compile(mm)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        active = [r for r in rows if (r.get("amount_base") or 0) > 0]
        if not active:
            return None
        total_mrr = sum(r["amount_base"] for r in active)
        return float(total_mrr / len(active))

    async def _simple_ltv(
        self,
        at: date | None,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> float | None:
        """Simple LTV = ARPU / average monthly logo churn rate.

        Monthly churn is computed per month in ``[start, end]`` and then
        averaged across months that had a starting cohort.  Using a single
        period-wide churn rate would understate LTV when the data doesn't
        predate ``start`` — the first month has no ``active_at_start``
        customers, so the period denominator collapses to 0.
        """
        from tidemill.metrics.retention.metric import _month_range, _to_month

        arpu = await self._arpu(at, spec)
        if arpu is None:
            return None

        months = _month_range(_to_month(start), _to_month(end))
        rates: list[float] = []
        for i, m_start in enumerate(months):
            if i + 1 < len(months):
                m_end = months[i + 1]
            else:
                y, mo = (
                    (m_start.year + 1, 1)
                    if m_start.month == 12
                    else (m_start.year, m_start.month + 1)
                )
                m_end = type(m_start)(y, mo, 1)
            r = await self.deps["churn"].query(
                {"start": m_start, "end": m_end, "type": "logo"},
                spec,
            )
            if r is not None:
                rates.append(float(r))

        if not rates:
            return None
        monthly_churn = sum(rates) / len(rates)
        if monthly_churn == 0:
            return None

        return float(arpu / monthly_churn)

    async def _cohort_ltv(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        """Average revenue per customer by cohort month.

        Cohort = month of a customer's first ``new`` MRR movement — matching
        the retention cohort definition.  Trials that never convert to paid
        MRR are excluded, so the cohort denominator is consistent with ARPU
        (both count customers with at least one active subscription,
        ``MRR > 0``).  Revenue is the sum of invoices paid in ``[start, end]``.
        """
        from tidemill.metrics.mrr.cubes import MRRMovementCube
        from tidemill.metrics.retention.metric import _to_month

        mm = MRRMovementCube

        nq = (
            mm.dimension("customer_id")
            + mm.measures.amount
            + mm.filter("movement_type", "=", "new")
            + mm.time_grain("occurred_at", "month")
        )
        if spec:
            nq = nq + mm.apply_spec(spec)
        nstmt, nparams = nq.compile(mm)
        nrows = (await self.db.execute(nstmt, nparams)).mappings().all()

        cohort_by_customer: dict[str, date] = {}
        for r in nrows:
            cid = r["customer_id"]
            month = _to_month(r["period"])
            prev = cohort_by_customer.get(cid)
            if prev is None or month < prev:
                cohort_by_customer[cid] = month

        start_m, end_m = _to_month(start), _to_month(end)
        cohort_by_customer = {
            cid: m for cid, m in cohort_by_customer.items() if start_m <= m <= end_m
        }
        if not cohort_by_customer:
            return []

        m = self.model
        iq = (
            m.measures.total_revenue
            + m.dimension("customer_id")
            + m.filter("paid_at", "between", (start, end))
        )
        if spec:
            iq = iq + m.apply_spec(spec)
        istmt, iparams = iq.compile(m)
        irows = (await self.db.execute(istmt, iparams)).mappings().all()

        revenue_by_customer: dict[str, int] = {
            r["customer_id"]: int(r["total_revenue"] or 0) for r in irows
        }

        per_cohort: dict[date, dict[str, int]] = {}
        for cid, cohort_m in cohort_by_customer.items():
            bucket = per_cohort.setdefault(cohort_m, {"count": 0, "revenue": 0})
            bucket["count"] += 1
            bucket["revenue"] += revenue_by_customer.get(cid, 0)

        return [
            {
                "cohort_month": cohort_m,
                "customer_count": data["count"],
                "total_revenue": data["revenue"],
                "avg_revenue_per_customer": (
                    data["revenue"] / data["count"] if data["count"] else 0
                ),
            }
            for cohort_m, data in sorted(per_cohort.items())
        ]
