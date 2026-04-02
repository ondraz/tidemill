"""Connector base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime

    from subscriptions.events import Event


class WebhookConnector(ABC):
    """Translates billing-system webhooks into internal events."""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        self.source_id = source_id
        self.config = config

    @property
    @abstractmethod
    def source_type(self) -> str: ...

    @abstractmethod
    def translate(self, webhook_payload: dict[str, Any]) -> list[Event]: ...

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        return True

    async def backfill(  # pragma: no cover
        self, since: datetime | None = None
    ) -> AsyncIterator[Event]:
        raise NotImplementedError
        yield  # noqa: RET503 — unreachable yield makes this an async generator


class DatabaseConnector(ABC):
    """Queries a billing engine's database directly (P1 — stub)."""

    def __init__(self, source_id: str, engine: Any) -> None:
        self.source_id = source_id
        self.engine = engine

    @property
    @abstractmethod
    def source_type(self) -> str: ...
