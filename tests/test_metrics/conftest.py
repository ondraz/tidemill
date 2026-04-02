"""Shared helpers for metric handler tests."""

from __future__ import annotations

from datetime import UTC, datetime

from subscriptions.events import Event, make_event_id

SRC = "src_1"
T0 = datetime(2026, 1, 15, tzinfo=UTC)
T1 = datetime(2026, 2, 15, tzinfo=UTC)
T2 = datetime(2026, 3, 15, tzinfo=UTC)
T3 = datetime(2026, 4, 15, tzinfo=UTC)

SRC_PG = "src_pg"


def make_evt(
    event_type: str,
    payload: dict,
    *,
    source_id: str = SRC,
    customer_id: str = "cus_1",
    external_id: str = "sub_1",
    occurred_at: datetime = T0,
) -> Event:
    return Event(
        id=make_event_id(source_id, event_type, external_id),
        source_id=source_id,
        type=event_type,
        occurred_at=occurred_at,
        published_at=occurred_at,
        customer_id=customer_id,
        payload=payload,
    )
