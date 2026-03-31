"""Metric registry: registration decorator, discovery, and dependency resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from subscriptions.metrics.base import Metric

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
