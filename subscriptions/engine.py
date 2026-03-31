"""MetricsEngine — discovers, initializes, and delegates to metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from subscriptions.metrics import (
    Metric,
    QuerySpec,
    discover_metrics,
    resolve_dependencies,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class MetricsEngine:
    """Central entry point for querying metrics.

    Discovers all ``@register``-ed metrics, resolves their dependency order,
    and initializes each with the database session and resolved dependencies.

    Usage::

        engine = MetricsEngine(db=async_session)
        result = await engine.query("mrr", {"query_type": "current"})
    """

    def __init__(
        self,
        db: AsyncSession,
        metrics: list[Metric] | None = None,
    ) -> None:
        self.db = db
        raw = metrics if metrics is not None else discover_metrics()
        ordered = resolve_dependencies(raw)

        self._metrics: dict[str, Metric] = {}
        for m in ordered:
            deps = {name: self._metrics[name] for name in m.dependencies}
            m.init(db=db, deps=deps)
            self._metrics[m.name] = m

    async def query(
        self,
        metric: str,
        params: dict[str, Any],
        spec: QuerySpec | None = None,
    ) -> Any:
        """Route a query to the named metric.

        Raises :class:`KeyError` if the metric is not registered.
        """
        if metric not in self._metrics:
            raise KeyError(
                f"No metric registered for '{metric}'. Available: {sorted(self._metrics)}"
            )
        return await self._metrics[metric].query(params, spec=spec)

    def available_metrics(self) -> list[str]:
        return sorted(self._metrics)
