"""Connector base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import date, datetime

    from fastapi import APIRouter
    from sqlalchemy.ext.asyncio import AsyncEngine

    from tidemill.events import Event


class WebhookConnector(ABC):
    """Translates billing-system webhooks into internal events."""

    def __init__(self, source_id: str, config: dict[str, Any]) -> None:
        self.source_id = source_id
        self.config = config

    @property
    @abstractmethod
    def source_type(self) -> str: ...

    @classmethod
    def router(cls) -> APIRouter | None:
        """Optional FastAPI router for this connector's webhook endpoint."""
        return None

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
    """Queries a billing engine's database directly (same-database mode).

    Used for billing engines that expose their PostgreSQL — Lago, Kill Bill —
    where Tidemill computes metrics by reading the source schema in place
    rather than ingesting events.  See ``docs/architecture/connectors.md``.
    """

    def __init__(self, source_id: str, engine: AsyncEngine) -> None:
        self.source_id = source_id
        self.engine = engine

    @property
    @abstractmethod
    def source_type(self) -> str: ...

    @abstractmethod
    async def get_active_subscriptions(self, at: date | None = None) -> list[dict[str, Any]]:
        """Active subscriptions with MRR contribution at *at* (default: now).

        Each row should include: ``external_id``, ``customer_external_id``,
        ``mrr_cents``, ``currency``, ``status``, ``started_at``.
        """
        ...

    @abstractmethod
    async def get_mrr_cents(self, at: date | None = None) -> int:
        """Total MRR in cents (original currency) at *at*."""
        ...

    @abstractmethod
    async def get_subscription_changes(self, start: date, end: date) -> list[dict[str, Any]]:
        """Subscription state changes in ``[start, end]`` (closed-closed).

        Each change should include: ``type`` (one of ``new`` / ``expansion`` /
        ``contraction`` / ``churn`` / ``reactivation``), ``amount_cents``,
        ``currency``, ``customer_external_id``, ``subscription_external_id``,
        ``occurred_at``.
        """
        ...

    @abstractmethod
    async def get_customers(self, at: date | None = None) -> list[dict[str, Any]]:
        """Customer records as of *at*."""
        ...

    @abstractmethod
    async def get_invoices(self, start: date, end: date) -> list[dict[str, Any]]:
        """Invoices issued in ``[start, end]`` (closed-closed)."""
        ...
