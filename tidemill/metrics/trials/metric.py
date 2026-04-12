"""TrialsMetric — query methods and event handler."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from tidemill.metrics.base import Metric, QuerySpec
from tidemill.metrics.registry import register
from tidemill.metrics.trials.cubes import TrialEventCube

if TYPE_CHECKING:
    from datetime import date

    from fastapi import APIRouter

    from tidemill.events import Event

_EVENT_TYPE_MAP = {
    "subscription.trial_started": "started",
    "subscription.trial_converted": "converted",
    "subscription.trial_expired": "expired",
}


@register
class TrialsMetric(Metric):
    name = "trials"
    model = TrialEventCube

    @property
    def router(self) -> APIRouter:
        from tidemill.metrics.trials.routes import router

        return router

    @property
    def event_types(self) -> list[str]:
        return [
            "subscription.trial_started",
            "subscription.trial_converted",
            "subscription.trial_expired",
        ]

    async def handle_event(self, event: Event) -> None:
        p = event.payload
        event_type = _EVENT_TYPE_MAP.get(event.type)
        if event_type is None:
            return

        await self.db.execute(
            text(
                "INSERT INTO metric_trial_event"
                " (id, event_id, source_id, customer_id,"
                "  subscription_id, event_type, occurred_at)"
                " VALUES (:id, :eid, :src, :cid, :sid, :et, :at)"
                " ON CONFLICT (event_id) DO NOTHING"
            ),
            {
                "id": str(uuid.uuid4()),
                "eid": event.id,
                "src": event.source_id,
                "cid": event.customer_id,
                "sid": p.get("external_id", ""),
                "et": event_type,
                "at": event.occurred_at,
            },
        )

    async def query(self, params: dict[str, Any], spec: QuerySpec | None = None) -> Any:
        match params.get("query_type"):
            case "conversion_rate":
                return await self._conversion_rate(params["start"], params["end"], spec)
            case "series":
                return await self._conversion_series(
                    params["start"],
                    params["end"],
                    params.get("interval", "month"),
                    spec,
                )
            case "funnel":
                return await self._funnel(params["start"], params["end"], spec)
            case other:
                raise ValueError(f"Unknown query_type: {other}")

    async def _conversion_rate(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> float | None:
        """Trial conversion rate = converted / started in time range."""
        m = self.model

        q = (
            m.measures.count
            + m.dimension("event_type")
            + m.filter("occurred_at", "between", (start, end))
        )
        if spec:
            q = q + m.apply_spec(spec)

        stmt, params = q.compile(m)
        result = await self.db.execute(stmt, params)
        by_type = {r["event_type"]: r["trial_count"] for r in result.mappings().all()}

        started = by_type.get("started", 0)
        if started == 0:
            return None
        return float(by_type.get("converted", 0) / started)

    async def _conversion_series(
        self,
        start: date,
        end: date,
        interval: str,
        spec: QuerySpec | None,
    ) -> list[dict[str, Any]]:
        """Conversion rate over time, grouped by period."""
        m = self.model

        q = (
            m.measures.count
            + m.dimension("event_type")
            + m.filter("occurred_at", "between", (start, end))
            + m.time_grain("occurred_at", interval)
        )
        if spec:
            q = q + m.apply_spec(spec)

        stmt, params = q.compile(m)
        result = await self.db.execute(stmt, params)

        # Group by period, compute rate per period
        by_period: dict[str, dict[str, int]] = {}
        for r in result.mappings().all():
            period_key = str(r["period"])
            by_period.setdefault(period_key, {})[r["event_type"]] = r["trial_count"]

        series = []
        for period, counts in sorted(by_period.items()):
            started = counts.get("started", 0)
            converted = counts.get("converted", 0)
            expired = counts.get("expired", 0)
            rate = converted / started if started else None
            series.append(
                {
                    "period": period,
                    "started": started,
                    "converted": converted,
                    "expired": expired,
                    "conversion_rate": rate,
                }
            )
        return series

    async def _funnel(
        self,
        start: date,
        end: date,
        spec: QuerySpec | None,
    ) -> dict[str, Any]:
        """Trial funnel: started, converted, expired counts."""
        m = self.model

        q = (
            m.measures.count
            + m.dimension("event_type")
            + m.filter("occurred_at", "between", (start, end))
        )
        if spec:
            q = q + m.apply_spec(spec)

        stmt, params = q.compile(m)
        result = await self.db.execute(stmt, params)
        by_type = {r["event_type"]: r["trial_count"] for r in result.mappings().all()}

        started = by_type.get("started", 0)
        converted = by_type.get("converted", 0)
        expired = by_type.get("expired", 0)

        return {
            "started": started,
            "converted": converted,
            "expired": expired,
            "conversion_rate": converted / started if started else None,
        }
