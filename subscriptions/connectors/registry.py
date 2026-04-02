"""Connector registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from subscriptions.connectors.base import WebhookConnector

_REGISTRY: dict[str, type[WebhookConnector]] = {}


def register(
    name: str,
) -> Callable[[type[WebhookConnector]], type[WebhookConnector]]:
    """Class decorator: ``@register("stripe")``."""

    def decorator(cls: type[WebhookConnector]) -> type[WebhookConnector]:
        if name in _REGISTRY:
            raise ValueError(f"Connector {name!r} already registered")
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_connector(name: str, *, source_id: str, config: dict[str, Any]) -> WebhookConnector:
    """Instantiate a registered connector by name."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown connector: {name!r}. Available: {list(_REGISTRY)}")
    return _REGISTRY[name](source_id=source_id, config=config)


def discover_connectors() -> list[str]:
    """Return names of all registered connectors."""
    return sorted(_REGISTRY)
