"""LtvMetric — query methods and event handler."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from tidemill.metrics.base import Metric, QuerySpec
from tidemill.metrics.ltv.cubes import LtvInvoiceCube
from tidemill.metrics.registry import register
from tidemill.segments.compiler import build_spec_fragment

logger = logging.getLogger(__name__)

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
        cur_raw = p.get("currency")
        if cur_raw:
            currency = cur_raw.upper()
        else:
            logger.warning(
                "LTV event missing currency, defaulting to USD",
                extra={
                    "event_id": event.id,
                    "event_type": event.type,
                    "source_id": event.source_id,
                },
            )
            currency = "USD"
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
    ) -> Any:
        """Average Revenue Per User = total active MRR / distinct active customers.

        When ``at`` is provided, the calculation is historical: the active
        set is every customer whose cumulative MRR movements before ``at``
        sum to a positive value, matching the ``[month-start, next-month-start)``
        cohort semantics used by MRR.  When ``at`` is ``None``, the snapshot
        table is used for an efficient current-state read.

        With ``spec.compare`` set, returns ``[{segment_id, arpu}, ...]``.
        """
        if at is not None:
            return await self._historical_arpu(at, spec)

        from tidemill.metrics.mrr.cubes import MRRSnapshotCube

        sm = MRRSnapshotCube
        q = sm.measures.mrr + sm.measures.customer_count + sm.where("s.mrr_base_cents", ">", 0)
        q = q + await build_spec_fragment(sm, spec, self.db)

        stmt, params = q.compile(sm)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        if spec and spec.compare:
            by_seg = {r["segment_id"]: r for r in rows}
            return [
                {
                    "segment_id": seg_id,
                    "arpu": (
                        float(by_seg[seg_id]["mrr"] / by_seg[seg_id]["customer_count"])
                        if seg_id in by_seg and by_seg[seg_id]["customer_count"]
                        else None
                    ),
                }
                for seg_id, _ in spec.compare
            ]

        row = rows[0] if rows else None
        if not row or not row["customer_count"]:
            return None
        return float(row["mrr"] / row["customer_count"])

    async def _historical_arpu(
        self,
        at: date,
        spec: QuerySpec | None,
    ) -> Any:
        from tidemill.metrics.mrr.cubes import MRRMovementCube

        # ``at`` is an inclusive end-of-day snapshot boundary (closed-closed
        # convention — see ``docs/definitions.md``). The filter layer coerces
        # the bare ``date`` to 23:59:59.999999 for the comparison.
        mm = MRRMovementCube
        q = mm.measures.amount + mm.dimension("customer_id") + mm.filter("occurred_at", "<=", at)
        q = q + await build_spec_fragment(mm, spec, self.db)

        stmt, params = q.compile(mm)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        if spec and spec.compare:
            # Group by segment — customer_id is a dim so each row is one
            # (segment_id, customer_id) pair.  ARPU per segment = sum MRR
            # among active / count of active.
            buckets: dict[str, list[float]] = {}
            for r in rows:
                amt = float(r.get("amount_base") or 0)
                if amt > 0:
                    buckets.setdefault(r["segment_id"], []).append(amt)
            return [
                {
                    "segment_id": seg_id,
                    "arpu": (
                        float(sum(buckets[seg_id]) / len(buckets[seg_id]))
                        if seg_id in buckets
                        else None
                    ),
                }
                for seg_id, _ in spec.compare
            ]

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
    ) -> Any:
        """Simple LTV = ARPU / average monthly logo churn rate.

        Monthly churn is computed per month in ``[start, end]`` and then
        averaged across months that had a starting cohort.  Using a single
        period-wide churn rate would understate LTV when the data doesn't
        predate ``start`` — the first month has no ``active_at_start``
        customers, so the period denominator collapses to 0.

        With ``spec.compare`` set, returns ``[{segment_id, ltv}, ...]`` —
        the per-segment ARPU and per-segment monthly churn come from the
        same compare payload, so the numerator and denominator line up.
        """
        from tidemill.metrics.retention.metric import _month_range, _to_month

        arpu = await self._arpu(at, spec)
        if arpu is None:
            return None

        has_compare = bool(spec and spec.compare)
        months = _month_range(_to_month(start), _to_month(end))

        if has_compare and spec is not None and spec.compare:
            rates_by_seg: dict[str, list[float]] = {}
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
                if isinstance(r, list):
                    for entry in r:
                        rate = entry.get("logo_churn_rate")
                        if rate is not None:
                            rates_by_seg.setdefault(entry["segment_id"], []).append(float(rate))

            arpu_by_seg = (
                {row["segment_id"]: row["arpu"] for row in arpu} if isinstance(arpu, list) else {}
            )
            out: list[dict[str, Any]] = []
            for seg_id, _ in spec.compare:
                a = arpu_by_seg.get(seg_id)
                seg_rates = rates_by_seg.get(seg_id, [])
                if a is None or not seg_rates:
                    out.append({"segment_id": seg_id, "ltv": None})
                    continue
                avg_churn = sum(seg_rates) / len(seg_rates)
                ltv = float(a / avg_churn) if avg_churn > 0 else None
                out.append({"segment_id": seg_id, "ltv": ltv})
            return out

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
            if r is not None and isinstance(r, (int, float)):
                rates.append(float(r))

        if not rates:
            return None
        monthly_churn = sum(rates) / len(rates)
        if monthly_churn == 0:
            return None

        # arpu can legitimately still be a scalar here (non-compare path)
        arpu_val = float(arpu) if isinstance(arpu, (int, float)) else 0.0
        return float(arpu_val / monthly_churn)

    async def _cohort_ltv(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        """Average revenue per customer by cohort month.

        The ``[start, end]`` window selects which cohorts to display (i.e. the
        rows returned). Revenue is the **cumulative lifetime revenue** from
        each cohort's customers — the sum of every invoice they have ever
        paid, not just invoices paid inside the display window. Bounding
        revenue by the display window would zero-out cohorts whose customers
        pay on a cadence that falls outside the selected range (e.g. annual
        invoices viewed through a quarterly window).

        Cohort = month of a customer's first ``new`` MRR movement — matching
        the retention cohort definition. Trials that never convert to paid
        MRR are excluded, so the cohort denominator is consistent with ARPU
        (both count customers with at least one active subscription,
        ``MRR > 0``).
        """
        from tidemill.metrics.mrr.cubes import MRRMovementCube
        from tidemill.metrics.retention.metric import _filter_only, _month_range, _to_month

        mm = MRRMovementCube
        # Cohort LTV with compare would mean a 3-D result (cohort × segment
        # × metrics) that the chart can't consume today — fall back to
        # segment-as-filter so the cohort axis stays 2-D.
        narrowed = _filter_only(spec)

        nq = (
            mm.dimension("customer_id")
            + mm.measures.amount
            + mm.filter("movement_type", "=", "new")
            + mm.time_grain("occurred_at", "month")
        )
        nq = nq + await build_spec_fragment(mm, narrowed, self.db)
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

        # Cumulative lifetime revenue per customer (no paid_at filter — see
        # docstring). The display window only selects which cohorts render.
        m = self.model
        iq = m.measures.total_revenue + m.dimension("customer_id")
        iq = iq + await build_spec_fragment(m, narrowed, self.db)
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

        # Emit one row per month in the display window — months without any
        # new-cohort customers render as zeros so the series is continuous
        # (no gaps in bar charts or heatmaps).
        return [
            {
                "cohort_month": cohort_m,
                "customer_count": per_cohort.get(cohort_m, {"count": 0})["count"],
                "total_revenue": per_cohort.get(cohort_m, {"revenue": 0})["revenue"],
                "avg_revenue_per_customer": (
                    per_cohort[cohort_m]["revenue"] / per_cohort[cohort_m]["count"]
                    if cohort_m in per_cohort and per_cohort[cohort_m]["count"] > 0
                    else 0
                ),
            }
            for cohort_m in _month_range(start_m, end_m)
        ]
