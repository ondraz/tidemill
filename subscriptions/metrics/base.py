"""Metric base class and query specification."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy import MetaData
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class QuerySpec:
    """Declarative query specification resolved against a metric's Cube.

    *dimensions* and *filters* reference names declared in the model.  The
    model validates them at query time and resolves the required joins.

    When *dimensions* is non-empty the metric returns a list of dicts (one per
    group).  When empty, a scalar or time series is returned as usual.
    """

    dimensions: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    granularity: str | None = None
    time_range: tuple[str, str] | None = None


class Metric(ABC):
    """Base class for all metrics.

    Subclasses must set ``name`` and implement :meth:`query`.
    """

    name: str = ""

    @property
    def dependencies(self) -> list[str]:
        """Names of metrics that must be initialized before this one."""
        return []

    def register_tables(self, metadata: MetaData) -> None:  # noqa: B027
        """Define metric-owned tables.  Called once at startup (optional override)."""

    def init(
        self,
        *,
        db: AsyncSession,
        deps: dict[str, Metric] | None = None,
    ) -> None:
        """Inject runtime dependencies.  Called by the engine after construction."""
        self.db = db
        self.deps = deps or {}

    @abstractmethod
    async def query(self, params: dict[str, Any], spec: QuerySpec | None = None) -> Any:
        """Answer a metric query.

        *params*  — query-type-specific (``query_type``, ``at``, ``start``, …).
        *spec*    — optional dimensions / filters from the caller.
        """
        ...
