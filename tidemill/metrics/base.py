"""Metric base class and query specification."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi import APIRouter
    from sqlalchemy import MetaData
    from sqlalchemy.ext.asyncio import AsyncSession

    from tidemill.events import Event
    from tidemill.metrics.query import Cube
    from tidemill.segments.model import SegmentDef


@dataclass
class QuerySpec:
    """Declarative query specification resolved against a metric's Cube.

    *dimensions* and *filters* reference names declared in the model.  The
    model validates them at query time and resolves the required joins.

    When *dimensions* is non-empty the metric returns a list of dicts (one per
    group).  When empty, a scalar or time series is returned as usual.

    *segment* is a universe filter — every row of the metric query is
    AND-restricted by the segment's conditions.  *compare* is a list of
    ``(segment_id, SegmentDef)`` pairs that produce a single query tagging
    each row with every branch it matches (CROSS JOIN VALUES + OR).  The
    two compose: ``segment`` narrows the universe, ``compare`` then slices
    it per branch.
    """

    dimensions: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    granularity: str | None = None
    time_range: tuple[str, str] | None = None
    segment: SegmentDef | None = None
    compare: tuple[tuple[str, SegmentDef], ...] | None = None


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

    @property
    def router(self) -> APIRouter | None:
        """Optional FastAPI router for this metric's endpoints."""
        return None

    @property
    def primary_cube(self) -> type[Cube]:
        """The cube exposed as this metric's filter/group-by surface.

        Used by the field-discovery endpoint and segment validation so the
        generic machinery doesn't have to hard-code which cube belongs to
        which metric.  Defaults to ``self.model`` — metrics with multiple
        cubes (e.g. churn, which owns both an event cube and a state cube)
        should override to pick the one that carries the richest dimension
        set for end-user filtering.
        """
        model: type[Cube] | None = getattr(self, "model", None)
        if model is None:
            raise NotImplementedError(
                f"{type(self).__name__} must define `model` or override `primary_cube`"
            )
        return model

    @property
    def event_types(self) -> list[str]:
        """Event types this metric subscribes to."""
        return []

    async def handle_event(self, event: Event) -> None:
        """Process a single event.  Must be idempotent."""
        raise NotImplementedError

    @abstractmethod
    async def query(self, params: dict[str, Any], spec: QuerySpec | None = None) -> Any:
        """Answer a metric query.

        *params*  — query-type-specific (``query_type``, ``at``, ``start``, …).
        *spec*    — optional dimensions / filters from the caller.
        """
        ...
