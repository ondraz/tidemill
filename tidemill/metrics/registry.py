"""Metric registry: registration decorator, discovery, and dependency resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tidemill.metrics.base import Metric
    from tidemill.metrics.query import Cube

_REGISTRY: dict[str, type[Metric]] = {}


def register(cls: type[Metric]) -> type[Metric]:
    """Class decorator that adds a Metric subclass to the global registry."""
    if not cls.name:
        raise TypeError(f"{cls.__name__} must set 'name' before registering")
    if cls.name in _REGISTRY:
        raise ValueError(f"Metric name '{cls.name}' is already registered")
    _REGISTRY[cls.name] = cls
    return cls


def discover_metrics() -> list[Metric]:
    """Instantiate all registered metrics (uninitialized)."""
    return [cls() for cls in _REGISTRY.values()]


def registered_names() -> list[str]:
    """Return the names of every registered metric, sorted."""
    return sorted(_REGISTRY)


def metric_primary_cube(name: str) -> type[Cube] | None:
    """Resolve *name* to its metric's :attr:`Metric.primary_cube`.

    Returns ``None`` for unknown metrics or metrics that don't expose a Cube
    (e.g. raw-SQL metrics like ``expenses``).  Used by generic routers (the
    ``/fields`` discovery endpoint, segment validation) so they stay
    plugin-agnostic — each metric advertises its own filter surface via
    the base-class contract rather than the router hard-coding a lookup.
    """
    cls = _REGISTRY.get(name)
    if cls is None:
        return None
    try:
        return cls().primary_cube
    except NotImplementedError:
        # Metric doesn't expose a Cube (raw-SQL implementation). Generic
        # filter/segment endpoints aren't applicable; metric-specific
        # routes still work.
        return None


def resolve_dependencies(metrics: list[Metric]) -> list[Metric]:
    """Topological sort by :attr:`Metric.dependencies`.  Raises on cycles."""
    by_name = {m.name: m for m in metrics}
    order: list[Metric] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise ValueError(f"Dependency cycle detected involving '{name}'")
        visiting.add(name)
        m = by_name[name]
        for dep in m.dependencies:
            if dep not in by_name:
                raise ValueError(f"Metric '{name}' depends on '{dep}' which is not registered")
            visit(dep)
        visiting.discard(name)
        visited.add(name)
        order.append(m)

    for name in by_name:
        visit(name)
    return order
