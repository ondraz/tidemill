"""Connector framework — re-exports and auto-discovery."""

# Auto-import built-in connectors so @register decorators fire.
import tidemill.connectors.quickbooks.connector as _quickbooks  # noqa: F401
import tidemill.connectors.stripe.connector as _stripe  # noqa: F401
from tidemill.connectors.base import DatabaseConnector, ExpenseConnector, WebhookConnector
from tidemill.connectors.registry import discover_connectors, get_connector, get_registry, register

__all__ = [
    "DatabaseConnector",
    "ExpenseConnector",
    "WebhookConnector",
    "discover_connectors",
    "get_connector",
    "get_registry",
    "register",
]
