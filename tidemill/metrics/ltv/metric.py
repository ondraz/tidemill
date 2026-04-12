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
        """Average Revenue Per User = total active MRR / distinct active customers."""
        where = "WHERE s.mrr_base_cents > 0"
        bind: dict[str, Any] = {}
        if at:
            where += " AND s.snapshot_at <= :at"
            bind["at"] = at

        result = await self.db.execute(
            text(
                "SELECT SUM(s.mrr_base_cents) AS mrr,"
                " COUNT(DISTINCT s.customer_id) AS customer_count"
                f" FROM metric_mrr_snapshot s {where}"
            ),
            bind,
        )
        row = result.mappings().first()
        if not row or not row["customer_count"]:
            return None
        return float(row["mrr"] / row["customer_count"])

    async def _simple_ltv(
        self,
        at: date | None,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> float | None:
        """Simple LTV = ARPU / monthly logo churn rate."""
        arpu = await self._arpu(at, spec)
        if arpu is None:
            return None

        churn_rate = await self.deps["churn"].query({"start": start, "end": end, "type": "logo"})
        if churn_rate is None or churn_rate == 0:
            return None

        return float(arpu / churn_rate)

    async def _cohort_ltv(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        """Average revenue per customer by cohort month."""
        m = self.model

        q = (
            m.measures.total_revenue
            + m.measures.customer_count
            + m.dimension("cohort_month")
            + m.filter("paid_at", "between", (start, end))
        )
        if spec:
            q = q + m.apply_spec(spec)

        stmt, params = q.compile(m)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        return [
            {
                "cohort_month": r["cohort_month"],
                "customer_count": r["customer_count"],
                "total_revenue": r["total_revenue"],
                "avg_revenue_per_customer": (
                    r["total_revenue"] / r["customer_count"] if r["customer_count"] else 0
                ),
            }
            for r in rows
        ]
