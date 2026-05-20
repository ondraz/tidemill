"""Dead-letter persistence for failed event handling.

Worker consumer tasks call :func:`record` whenever ``handle_event`` raises,
so the failed event payload is preserved for later replay (e.g. once a
missing ``fx_rate`` row is backfilled). One row per ``(event_id, consumer)``
pair — each consumer (state, metric:mrr, …) tracks its own failures.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

from tidemill.connectors.base import CanonicalEnumViolation
from tidemill.fx import FxRateMissingError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from tidemill.events import Event


def classify_error(exc: BaseException) -> str:
    """Return a short, queryable tag for *exc*.

    Adding a new tag here is the supported way to surface a new class of
    transient failure in dashboards / replay tooling.
    """
    if isinstance(exc, FxRateMissingError):
        return "fx_rate_missing"
    if isinstance(exc, CanonicalEnumViolation):
        return "canonical_enum_violation"
    return "unknown"


async def record(
    session: AsyncSession,
    event: Event,
    consumer: str,
    error: BaseException,
) -> None:
    """Persist a dead-letter row for *event* on this *consumer* stream.

    Idempotent on ``(event_id, consumer)`` — a re-delivery that fails the
    same way only refreshes ``error_message`` and ``dead_lettered_at``.
    """
    await session.execute(
        text(
            "INSERT INTO dead_letter_event"
            " (id, event_id, source_id, event_type, consumer,"
            "  error_type, error_message, payload, occurred_at, dead_lettered_at)"
            " VALUES (:id, :eid, :src, :etype, :consumer,"
            "  :err_type, :err_msg, :payload, :occ, :now)"
            " ON CONFLICT ON CONSTRAINT uq_dlq_event_consumer DO UPDATE SET"
            "  error_type = EXCLUDED.error_type,"
            "  error_message = EXCLUDED.error_message,"
            "  dead_lettered_at = EXCLUDED.dead_lettered_at,"
            "  resolved_at = NULL"
        ),
        {
            "id": str(uuid.uuid4()),
            "eid": event.id,
            "src": event.source_id,
            "etype": event.type,
            "consumer": consumer,
            "err_type": classify_error(error),
            "err_msg": str(error),
            "payload": json.dumps(event.payload),
            "occ": event.occurred_at,
            "now": datetime.now(UTC),
        },
    )
    await session.commit()


async def mark_resolved(session: AsyncSession, event_id: str, consumer: str) -> None:
    """Mark a dead-letter row resolved after a successful replay."""
    await session.execute(
        text(
            "UPDATE dead_letter_event"
            " SET resolved_at = :now"
            " WHERE event_id = :eid AND consumer = :consumer"
        ),
        {"now": datetime.now(UTC), "eid": event_id, "consumer": consumer},
    )
    await session.commit()
