"""RetentionMetric — query methods and event handler."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import text

from tidemill.metrics.base import Metric, QuerySpec
from tidemill.metrics.registry import register
from tidemill.metrics.retention.cubes import RetentionCohortCube
from tidemill.segments.compiler import build_spec_fragment

if TYPE_CHECKING:
    from fastapi import APIRouter

    from tidemill.events import Event


def _to_month(value: Any) -> date:
    """Normalize a value to the first day of its month."""
    if isinstance(value, datetime):
        value = value.date()
    return cast("date", value.replace(day=1))


def _filter_only(spec: QuerySpec | None) -> QuerySpec | None:
    """Return a spec with compare stripped — segment filter kept.

    Used by the cohort-matrix path: the matrix's three axes are
    ``cohort_month`` × ``active_month`` × customer; adding segment_id as a
    fourth axis would produce a 4-D result that the current chart can't
    render.  Callers get segment-*filtered* retention (universe narrowed)
    while compare silently falls back to the union of branches.
    """
    if spec is None:
        return None
    if not spec.compare:
        return spec
    from copy import copy

    clone = copy(spec)
    clone.compare = None
    return clone


def _month_range(first: date, last: date) -> list[date]:
    """Inclusive list of month-starts from ``first`` to ``last``."""
    months: list[date] = []
    cur = first
    while cur <= last:
        months.append(cur)
        year, month = (cur.year + 1, 1) if cur.month == 12 else (cur.year, cur.month + 1)
        cur = date(year, month, 1)
    return months


@register
class RetentionMetric(Metric):
    name = "retention"
    model = RetentionCohortCube

    @property
    def router(self) -> APIRouter:
        from tidemill.metrics.retention.routes import router

        return router

    @property
    def dependencies(self) -> list[str]:
        return ["mrr"]

    @property
    def event_types(self) -> list[str]:
        return [
            "subscription.created",
            "subscription.activated",
            "subscription.reactivated",
        ]

    async def handle_event(self, event: Event) -> None:
        cohort_month = event.occurred_at.date().replace(day=1)
        active_month = cohort_month  # same month

        match event.type:
            case "subscription.created" | "subscription.activated":
                # Assign cohort — ON CONFLICT DO NOTHING keeps the first month
                await self.db.execute(
                    text(
                        "INSERT INTO metric_retention_cohort"
                        " (id, source_id, customer_id, cohort_month)"
                        " VALUES (:id, :src, :cid, :cm)"
                        " ON CONFLICT ON CONSTRAINT uq_retention_cohort_customer"
                        " DO NOTHING"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "src": event.source_id,
                        "cid": event.customer_id,
                        "cm": cohort_month,
                    },
                )

        # Record activity for the month (all event types)
        await self.db.execute(
            text(
                "INSERT INTO metric_retention_activity"
                " (id, source_id, customer_id, active_month)"
                " VALUES (:id, :src, :cid, :am)"
                " ON CONFLICT ON CONSTRAINT uq_retention_activity DO NOTHING"
            ),
            {
                "id": str(uuid.uuid4()),
                "src": event.source_id,
                "cid": event.customer_id,
                "am": active_month,
            },
        )

    async def query(self, params: dict[str, Any], spec: QuerySpec | None = None) -> Any:
        match params.get("query_type", "cohort_matrix"):
            case "cohort_matrix":
                return await self._cohort_matrix(
                    params["start"],
                    params["end"],
                    spec,
                )
            case "nrr":
                return await self._nrr(params["start"], params["end"], spec)
            case "grr":
                return await self._grr(params["start"], params["end"], spec)
            case other:
                raise ValueError(f"Unknown query_type: {other}")

    async def _cohort_matrix(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        """Cohort retention derived from MRR movements.

        Cohort is the first month a customer had a ``new`` movement.  Trial
        customers whose subscription was created earlier than their first
        paid month end up in the month they actually became revenue
        generating.  Reactivations do not reassign cohort — a customer who
        churned and returned stays in their original cohort and shows as
        re-activated in the retention matrix for the month they came back.

        Activity: a customer is "active in month M" iff their cumulative
        MRR through end-of-M is positive.
        """
        from tidemill.metrics.mrr.cubes import MRRMovementCube

        mm = MRRMovementCube

        # 1. Cohort = month of first `new` movement, per customer.
        # Apply segment (universe filter) so the cohort matrix is scoped.
        # Compare on a cohort matrix would return per-segment matrices;
        # not supported in MVP — treat compare like a plain segment list
        # (matrix shows the union of customers matching any branch).
        segment_frag = await build_spec_fragment(mm, _filter_only(spec), self.db)
        nq = (
            mm.dimension("customer_id")
            + mm.measures.amount
            + mm.filter("movement_type", "=", "new")
            + mm.time_grain("occurred_at", "month")
            + segment_frag
        )
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

        # 2. Monthly MRR movements per customer, through period end.
        # ``end`` is the last inclusive day — the filter layer coerces it to
        # end-of-day so events late on ``end`` are captured.
        mq = (
            mm.dimension("customer_id")
            + mm.measures.amount
            + mm.filter("occurred_at", "<=", end)
            + mm.time_grain("occurred_at", "month")
            + segment_frag
        )
        mstmt, mparams = mq.compile(mm)
        mrows = (await self.db.execute(mstmt, mparams)).mappings().all()

        movements: dict[str, dict[date, int]] = {}
        for r in mrows:
            cid = r["customer_id"]
            month = _to_month(r["period"])
            movements.setdefault(cid, {})[month] = int(r["amount_base"] or 0)

        # 3. Per-customer active months: cumulative MRR > 0 at end-of-month
        months = _month_range(min(cohort_by_customer.values()), _to_month(end))

        active_months_by_customer: dict[str, set[date]] = {}
        for cid, cohort_m in cohort_by_customer.items():
            cum = 0
            active: set[date] = {cohort_m}
            for month in months:
                cum += movements.get(cid, {}).get(month, 0)
                if month > cohort_m and cum > 0:
                    active.add(month)
            active_months_by_customer[cid] = active

        # 4. Aggregate to (cohort_month, active_month) counts
        cohort_sizes: dict[date, int] = {}
        for cohort_m in cohort_by_customer.values():
            cohort_sizes[cohort_m] = cohort_sizes.get(cohort_m, 0) + 1

        active_counts: dict[tuple[date, date], int] = {}
        for cid, cohort_m in cohort_by_customer.items():
            for active_m in active_months_by_customer[cid]:
                key = (cohort_m, active_m)
                active_counts[key] = active_counts.get(key, 0) + 1

        return [
            {
                "cohort_month": cohort_m,
                "active_month": active_m,
                "cohort_size": cohort_sizes[cohort_m],
                "active_count": count,
            }
            for (cohort_m, active_m), count in sorted(active_counts.items())
        ]

    async def _nrr(self, start: date, end: date, spec: QuerySpec | None = None) -> Any:
        """Net Revenue Retention = (start_mrr + expansion - contraction - churn) / start_mrr."""
        return await self._revenue_retention(start, end, include_expansion=True, spec=spec)

    async def _grr(self, start: date, end: date, spec: QuerySpec | None = None) -> Any:
        """Gross Revenue Retention = (start_mrr - contraction - churn) / start_mrr."""
        return await self._revenue_retention(start, end, include_expansion=False, spec=spec)

    async def _revenue_retention(
        self,
        start: date,
        end: date,
        *,
        include_expansion: bool,
        spec: QuerySpec | None = None,
    ) -> Any:
        from tidemill.metrics.mrr.cubes import MRRMovementCube

        mm = MRRMovementCube
        has_compare = bool(spec and spec.compare)

        # Start-of-period MRR = cumulative movements before `start`.
        # (The snapshot table stores current state only, not a time series.)
        sq = mm.measures.amount + mm.filter("occurred_at", "<", start)
        sq = sq + await build_spec_fragment(mm, spec, self.db)
        sstmt, sparams = sq.compile(mm)
        srows = (await self.db.execute(sstmt, sparams)).mappings().all()

        # Movements in [start, end] (closed-closed; filter layer extends
        # `end` to end-of-day).
        mq = (
            mm.measures.amount
            + mm.dimension("movement_type")
            + mm.filter("occurred_at", "between", (start, end))
        )
        mq = mq + await build_spec_fragment(mm, spec, self.db)
        stmt, params = mq.compile(mm)
        result = await self.db.execute(stmt, params)
        mrows = result.mappings().all()

        if has_compare and spec is not None and spec.compare:
            start_by_seg = {r["segment_id"]: float(r["amount_base"] or 0) for r in srows}
            by_seg_type: dict[str, dict[str, float]] = {}
            for r in mrows:
                by_seg_type.setdefault(r["segment_id"], {})[r["movement_type"]] = float(
                    r["amount_base"] or 0
                )
            out: list[dict[str, Any]] = []
            for seg_id, _ in spec.compare:
                s_mrr = start_by_seg.get(seg_id, 0.0)
                if s_mrr <= 0:
                    out.append({"segment_id": seg_id, "retention_rate": None})
                    continue
                bt = by_seg_type.get(seg_id, {})
                contraction = abs(bt.get("contraction", 0))
                churn = abs(bt.get("churn", 0))
                if include_expansion:
                    expansion = bt.get("expansion", 0) + bt.get("reactivation", 0)
                    rate = float((s_mrr + expansion - contraction - churn) / s_mrr)
                else:
                    rate = float((s_mrr - contraction - churn) / s_mrr)
                out.append({"segment_id": seg_id, "retention_rate": rate})
            return out

        start_mrr = int(srows[0]["amount_base"] or 0) if srows else 0
        if start_mrr <= 0:
            return None

        by_type = {r["movement_type"]: r["amount_base"] for r in mrows}

        contraction = abs(by_type.get("contraction", 0))
        churn = abs(by_type.get("churn", 0))

        if include_expansion:
            expansion = by_type.get("expansion", 0) + by_type.get("reactivation", 0)
            return float((start_mrr + expansion - contraction - churn) / start_mrr)

        return float((start_mrr - contraction - churn) / start_mrr)
