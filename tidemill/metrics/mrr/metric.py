"""MrrMetric — query methods and event handler."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from tidemill.metrics.base import Metric, QuerySpec
from tidemill.metrics.mrr.cubes import MRRMovementCube, MRRSnapshotCube
from tidemill.metrics.registry import register
from tidemill.segments.compiler import build_spec_fragment

logger = logging.getLogger(__name__)


def _resolve_currency(event: Event, kind: str) -> str:
    """Read currency from an event payload, defaulting to USD with a warning.

    Why: silently defaulting to USD lets a translator regression corrupt
    metric tables for non-USD subscribers. We still fall back so a single
    bad event doesn't crash the consumer, but the warning surfaces the gap.
    """
    cur = event.payload.get("currency")
    if cur:
        return str(cur).upper()
    logger.warning(
        "%s event missing currency, defaulting to USD",
        kind,
        extra={
            "event_id": event.id,
            "event_type": event.type,
            "source_id": event.source_id,
        },
    )
    return "USD"


if TYPE_CHECKING:
    from datetime import date

    import pandas as pd
    from fastapi import APIRouter

    from tidemill.events import Event


def _align_to_period_start(ts: pd.Timestamp, interval: str) -> pd.Timestamp:
    """Snap a timestamp back to the start of the period it falls in.

    Matches PostgreSQL's DATE_TRUNC semantics — weekly periods are
    Monday-anchored (ISO week).
    """
    import pandas as pd

    if interval == "day":
        return ts.normalize()
    if interval == "week":
        return (ts - pd.Timedelta(days=ts.weekday())).normalize()
    if interval == "month":
        return pd.Timestamp(ts.year, ts.month, 1)
    if interval == "quarter":
        q = (ts.month - 1) // 3
        return pd.Timestamp(ts.year, q * 3 + 1, 1)
    if interval == "year":
        return pd.Timestamp(ts.year, 1, 1)
    return ts.normalize()


@register
class MrrMetric(Metric):
    name = "mrr"
    model = MRRSnapshotCube
    movement_model = MRRMovementCube

    @property
    def router(self) -> APIRouter:
        from tidemill.metrics.mrr.routes import router

        return router

    @property
    def event_types(self) -> list[str]:
        return [
            "subscription.created",
            "subscription.activated",
            "subscription.changed",
            "subscription.churned",
            "subscription.reactivated",
            "subscription.paused",
            "subscription.resumed",
        ]

    async def handle_event(self, event: Event) -> None:
        from tidemill.fx import to_base_cents

        p = event.payload
        ext_id = p["external_id"]

        match event.type:
            case "subscription.created":
                # Snapshot only — the "new" movement is created by
                # subscription.activated so we don't double-count
                # trials that later convert.
                mrr = p.get("mrr_cents", 0)
                currency = _resolve_currency(event, "MRR")
                mrr_base = await to_base_cents(mrr, currency, event.occurred_at.date(), self.db)
                await self._upsert_snapshot(
                    event,
                    ext_id,
                    mrr,
                    mrr_base,
                    currency,
                )

            case "subscription.activated":
                mrr = p.get("mrr_cents", 0)
                currency = _resolve_currency(event, "MRR")
                mrr_base = await to_base_cents(mrr, currency, event.occurred_at.date(), self.db)
                movement_type = await self._classify_activation(event)
                await self._upsert_snapshot(
                    event,
                    ext_id,
                    mrr,
                    mrr_base,
                    currency,
                )
                await self._append_movement(
                    event,
                    ext_id,
                    movement_type,
                    mrr,
                    mrr_base,
                    currency,
                )

            case "subscription.changed":
                prev_mrr = p.get("prev_mrr_cents", 0)
                new_mrr = p.get("new_mrr_cents", 0)
                currency = _resolve_currency(event, "MRR")
                new_mrr_base = await to_base_cents(
                    new_mrr, currency, event.occurred_at.date(), self.db
                )
                await self._upsert_snapshot(
                    event,
                    ext_id,
                    new_mrr,
                    new_mrr_base,
                    currency,
                )
                delta = new_mrr - prev_mrr
                delta_base = await to_base_cents(
                    delta, currency, event.occurred_at.date(), self.db
                )
                movement = "expansion" if delta > 0 else "contraction"
                await self._append_movement(
                    event,
                    ext_id,
                    movement,
                    delta,
                    delta_base,
                    currency,
                )

            case "subscription.churned" | "subscription.paused":
                prev_mrr = p.get("prev_mrr_cents", 0) or p.get("mrr_cents", 0)
                currency = _resolve_currency(event, "MRR")
                prev_mrr_base = await to_base_cents(
                    prev_mrr, currency, event.occurred_at.date(), self.db
                )
                await self._upsert_snapshot(event, ext_id, 0, 0, currency)
                await self._append_movement(
                    event,
                    ext_id,
                    "churn",
                    -prev_mrr,
                    -prev_mrr_base,
                    currency,
                )

            case "subscription.reactivated" | "subscription.resumed":
                mrr = p.get("mrr_cents", 0)
                currency = _resolve_currency(event, "MRR")
                mrr_base = await to_base_cents(mrr, currency, event.occurred_at.date(), self.db)
                await self._upsert_snapshot(
                    event,
                    ext_id,
                    mrr,
                    mrr_base,
                    currency,
                )
                await self._append_movement(
                    event,
                    ext_id,
                    "reactivation",
                    mrr,
                    mrr_base,
                    currency,
                )

    async def _classify_activation(self, event: Event) -> str:
        """Classify a ``subscription.activated`` event as ``new`` or ``reactivation``.

        A customer is reactivating if they had prior MRR movements but their
        cumulative MRR was zero just before this event (i.e., all earlier
        subscriptions were churned or paused). A brand-new customer or one
        with already-active subscriptions is recorded as ``new``.
        """
        result = await self.db.execute(
            text(
                "SELECT COUNT(*) AS n,"
                "       COALESCE(SUM(amount_base_cents), 0) AS cum"
                " FROM metric_mrr_movement"
                " WHERE source_id = :src"
                "   AND customer_id = :cid"
                "   AND occurred_at < :now"
            ),
            {
                "src": event.source_id,
                "cid": event.customer_id,
                "now": event.occurred_at,
            },
        )
        row = result.mappings().one()
        if int(row["n"]) > 0 and int(row["cum"] or 0) <= 0:
            return "reactivation"
        return "new"

    async def _upsert_snapshot(
        self,
        event: Event,
        subscription_ext_id: str,
        mrr_cents: int,
        mrr_base_cents: int,
        currency: str,
    ) -> None:
        await self.db.execute(
            text(
                "INSERT INTO metric_mrr_snapshot"
                " (id, source_id, customer_id, subscription_id,"
                "  mrr_cents, mrr_base_cents, currency, snapshot_at)"
                " VALUES (:id, :src, :cid, :sid, :mrr, :mrrb, :cur, :at)"
                " ON CONFLICT ON CONSTRAINT uq_mrr_snapshot_sub DO UPDATE SET"
                "  mrr_cents = EXCLUDED.mrr_cents,"
                "  mrr_base_cents = EXCLUDED.mrr_base_cents,"
                "  currency = EXCLUDED.currency,"
                "  snapshot_at = EXCLUDED.snapshot_at"
            ),
            {
                "id": str(uuid.uuid4()),
                "src": event.source_id,
                "cid": event.customer_id,
                "sid": subscription_ext_id,
                "mrr": mrr_cents,
                "mrrb": mrr_base_cents,
                "cur": currency.upper(),
                "at": event.occurred_at,
            },
        )

    async def _append_movement(
        self,
        event: Event,
        subscription_ext_id: str,
        movement_type: str,
        amount_cents: int,
        amount_base_cents: int,
        currency: str,
    ) -> None:
        await self.db.execute(
            text(
                "INSERT INTO metric_mrr_movement"
                " (id, event_id, source_id, customer_id, subscription_id,"
                "  movement_type, amount_cents, amount_base_cents, currency, occurred_at)"
                " VALUES (:id, :eid, :src, :cid, :sid, :mt, :amt, :amtb, :cur, :at)"
                " ON CONFLICT (event_id) DO NOTHING"
            ),
            {
                "id": str(uuid.uuid4()),
                "eid": event.id,
                "src": event.source_id,
                "cid": event.customer_id,
                "sid": subscription_ext_id,
                "mt": movement_type,
                "amt": amount_cents,
                "amtb": amount_base_cents,
                "cur": currency.upper(),
                "at": event.occurred_at,
            },
        )

    async def query(self, params: dict[str, Any], spec: QuerySpec | None = None) -> Any:
        match params.get("query_type"):
            case "current":
                return await self._current_mrr(params.get("at"), spec)
            case "series":
                return await self._mrr_series(
                    params["start"],
                    params["end"],
                    params.get("interval", "month"),
                    spec,
                )
            case "breakdown":
                return await self._mrr_breakdown(params["start"], params["end"], spec)
            case "waterfall":
                return await self._mrr_waterfall(
                    params["start"],
                    params["end"],
                    params.get("interval", "month"),
                    spec,
                )
            case "arr":
                if params.get("start") and params.get("end"):
                    series = await self._mrr_series(
                        params["start"],
                        params["end"],
                        params.get("interval", "month"),
                        spec,
                    )
                    return [
                        {
                            **{k: v for k, v in row.items() if k != "amount_base"},
                            "arr": float(row.get("amount_base") or 0) * 12,
                        }
                        for row in series
                    ]
                mrr = await self._current_mrr(params.get("at"), spec)
                if isinstance(mrr, list):
                    return [{**row, "arr": row.get("mrr", 0) * 12} for row in mrr]
                return mrr * 12
            case other:
                raise ValueError(f"Unknown query_type: {other}")

    async def _current_mrr(
        self,
        at: date | None,
        spec: QuerySpec | None,
    ) -> Any:
        use_original = spec and "currency" in (spec.dimensions or [])
        has_compare = bool(spec and spec.compare)

        if at is not None:
            # Historical MRR: cumulative sum of movements through end-of-day
            # ``at``. The snapshot table only stores the latest state per
            # subscription, so filtering by snapshot_at would miss subscriptions
            # modified later. The filter layer coerces a bare ``date`` upper
            # bound to the last microsecond of the day (closed-closed
            # convention — see ``docs/definitions.md``).
            mm = self.movement_model
            measure = mm.measures.amount_original if use_original else mm.measures.amount
            dq = measure + mm.filter("occurred_at", "<=", at)
            dq = dq + await build_spec_fragment(mm, spec, self.db)
            stmt, params = dq.compile(mm)
            result = await self.db.execute(stmt, params)
            rows = result.mappings().all()
            src = "amount_original" if use_original else "amount_base"
            if not spec or (not spec.dimensions and not has_compare):
                return float(rows[0][src] or 0) if rows else 0
            return [{("mrr" if k == src else k): v for k, v in dict(r).items()} for r in rows]

        # Current MRR: snapshot table (efficient single-table query)
        m = self.model
        measure = m.measures.mrr_original if use_original else m.measures.mrr
        q = measure + m.where("s.mrr_base_cents", ">", 0)
        q = q + await build_spec_fragment(m, spec, self.db)
        stmt, params = q.compile(m)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()
        if not spec or (not spec.dimensions and not has_compare):
            return rows[0]["mrr"] if rows else 0
        return [dict(r) for r in rows]

    async def _mrr_series(
        self,
        start: date,
        end: date,
        interval: str,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        mm = self.movement_model

        q = (
            mm.measures.amount
            + mm.filter("occurred_at", "between", (start, end))
            + mm.time_grain("occurred_at", interval)
        )
        q = q + await build_spec_fragment(mm, spec, self.db)

        stmt, params = q.compile(mm)
        result = await self.db.execute(stmt, params)
        return [dict(r) for r in result.mappings().all()]

    async def _mrr_waterfall(
        self,
        start: date,
        end: date,
        interval: str,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        import pandas as pd

        # Map analytics interval → pandas freq alias for period enumeration.
        # These match PostgreSQL DATE_TRUNC so client-side period keys
        # (from ``periodStarts``) line up with the grouping the query
        # produces — the week anchor is Monday to match DATE_TRUNC('week').
        freq_by_interval = {
            "day": "D",
            "week": "W-MON",
            "month": "MS",
            "quarter": "QS",
            "year": "YS",
        }
        freq = freq_by_interval.get(interval, "MS")

        # Align ``start`` to the period it falls in. ``pd.date_range`` with
        # an anchored freq skips any partial opening period (e.g. MS from
        # Jan 15 yields Feb 1, dropping January), so we snap start back to
        # the period boundary before enumerating.
        period_start = _align_to_period_start(pd.Timestamp(start), interval)
        periods = pd.date_range(period_start, end, freq=freq, inclusive="both")
        if len(periods) < 2:
            return []

        baseline = await self._current_mrr(start, spec)
        if isinstance(baseline, list):
            baseline = sum(r.get("mrr", 0) or 0 for r in baseline)
        baseline = baseline or 0

        mm = self.movement_model
        q = (
            mm.measures.amount
            + mm.dimension("movement_type")
            + mm.filter("occurred_at", "between", (start, end))
            + mm.time_grain("occurred_at", interval)
        )
        q = q + await build_spec_fragment(mm, spec, self.db)

        stmt, params = q.compile(mm)
        result = await self.db.execute(stmt, params)
        rows = result.mappings().all()

        movements_by_period: dict[str, dict[str, float]] = {}
        for r in rows:
            period_key = r["period"].strftime("%Y-%m-%d")
            mt = r["movement_type"]
            movements_by_period.setdefault(period_key, {})[mt] = float(r["amount_base"])
        movement_types = ["new", "expansion", "contraction", "churn", "reactivation"]

        waterfall = []
        ending_mrr = float(baseline)
        for period in periods:
            period_key = period.strftime("%Y-%m-%d")
            mvmt = movements_by_period.get(period_key, {})
            starting_mrr = ending_mrr
            net_change = sum(mvmt.get(mt, 0) for mt in movement_types)
            ending_mrr = starting_mrr + net_change

            entry: dict[str, Any] = {
                "period": period_key,
                "starting_mrr": round(starting_mrr, 2),
            }
            for mt in movement_types:
                entry[mt] = round(mvmt.get(mt, 0), 2)
            entry["net_change"] = round(net_change, 2)
            entry["ending_mrr"] = round(ending_mrr, 2)
            waterfall.append(entry)

        return waterfall

    async def _mrr_breakdown(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        mm = self.movement_model

        q = (
            mm.measures.amount
            + mm.dimension("movement_type")
            + mm.filter("occurred_at", "between", (start, end))
        )
        q = q + await build_spec_fragment(mm, spec, self.db)

        stmt, params = q.compile(mm)
        result = await self.db.execute(stmt, params)
        return [dict(r) for r in result.mappings().all()]
