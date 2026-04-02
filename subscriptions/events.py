"""Internal event schema and serialization."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

# Fixed namespace for deterministic event IDs (UUID v5).
_EVENT_NAMESPACE = uuid.UUID("d4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a")


@dataclass(frozen=True)
class Event:
    """Immutable internal event.

    Every billing-system change is translated into one or more events by a
    connector.  Events flow through Kafka and are processed by the core state
    manager and metric handlers.
    """

    id: str
    source_id: str
    type: str
    occurred_at: datetime
    published_at: datetime
    customer_id: str
    payload: dict[str, Any]


def make_event_id(source_id: str, event_type: str, external_id: str) -> str:
    """UUID v5 from source + type + external ID — deterministic, idempotent."""
    return str(uuid.uuid5(_EVENT_NAMESPACE, f"{source_id}:{event_type}:{external_id}"))


def to_json(event: Event) -> bytes:
    """Serialize an event for Kafka."""
    d = asdict(event)
    d["occurred_at"] = event.occurred_at.isoformat()
    d["published_at"] = event.published_at.isoformat()
    return json.dumps(d).encode()


def from_json(data: bytes) -> Event:
    """Deserialize an event from Kafka."""
    d = json.loads(data)
    d["occurred_at"] = datetime.fromisoformat(d["occurred_at"])
    d["published_at"] = datetime.fromisoformat(d["published_at"])
    return Event(**d)
