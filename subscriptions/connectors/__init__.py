"""Connector framework — re-exports and auto-discovery."""

# Auto-import built-in connectors so @register decorators fire.
import subscriptions.connectors.stripe as _stripe  # noqa: F401
from subscriptions.connectors.base import DatabaseConnector, WebhookConnector
from subscriptions.connectors.registry import discover_connectors, get_connector, register

__all__ = [
    "DatabaseConnector",
    "WebhookConnector",
    "discover_connectors",
    "get_connector",
    "register",
]
