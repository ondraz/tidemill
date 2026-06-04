"""Bootstrap ``connector_source`` rows for the configured connectors.

Every billing entity (subscription, customer, invoice, …) and every event
carries a ``source_id`` that is an FK to ``connector_source.id``. Before a
webhook handler or the event consumer can persist anything for a connector,
its source row must exist. This module ensures the rows for the connectors
this deployment runs.

A deployment lists its connectors via ``TIDEMILL_CONNECTORS`` (comma-separated,
e.g. ``stripe,chargebee``). ``TIDEMILL_CONNECTOR`` (singular) is the legacy
single-source form and the fallback. Both the API (in its lifespan) and the
worker call :func:`ensure_connector_sources`, so the rows exist no matter which
process starts first.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncConnection

# Canonical id/type/name for each connector we can bootstrap. The id doubles as
# the default ``source_id`` used by webhook handlers (e.g. the Chargebee webhook
# defaults to ``source_id="chargebee"``), so it must match these ids.
CONNECTOR_DEFAULTS: dict[str, dict[str, str]] = {
    "stripe": {"id": "stripe", "type": "stripe", "name": "Stripe"},
    "chargebee": {"id": "chargebee", "type": "chargebee", "name": "Chargebee"},
    "lago": {"id": "lago", "type": "lago", "name": "Lago"},
    "killbill": {"id": "killbill", "type": "killbill", "name": "Kill Bill"},
}


def configured_connectors() -> list[str]:
    """Return the lowercased connector names this deployment should bootstrap.

    Reads ``TIDEMILL_CONNECTORS`` (comma-separated) first, falling back to the
    legacy singular ``TIDEMILL_CONNECTOR``, then to ``stripe``.
    """
    raw = os.environ.get("TIDEMILL_CONNECTORS") or os.environ.get("TIDEMILL_CONNECTOR", "stripe")
    return [c.strip().lower() for c in raw.split(",") if c.strip()]


async def ensure_connector_sources(
    conn: AsyncConnection,
    connectors: list[str] | None = None,
) -> None:
    """Idempotently insert a ``connector_source`` row for each configured connector.

    *connectors* defaults to :func:`configured_connectors`. Unknown names are
    skipped. Safe to call repeatedly — uses ``ON CONFLICT (id) DO NOTHING``.
    """
    for name in connectors if connectors is not None else configured_connectors():
        default = CONNECTOR_DEFAULTS.get(name)
        if default is not None:
            await conn.execute(
                text(
                    "INSERT INTO connector_source (id, type, name, created_at)"
                    " VALUES (:id, :type, :name, NOW())"
                    " ON CONFLICT (id) DO NOTHING"
                ),
                default,
            )
