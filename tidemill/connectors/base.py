"""Connector base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import datetime

    from fastapi import APIRouter

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
    """Queries a billing engine's database directly (P1 — stub)."""

    def __init__(self, source_id: str, engine: Any) -> None:
        self.source_id = source_id
        self.engine = engine

    @property
    @abstractmethod
    def source_type(self) -> str: ...


# Canonical enums every ExpenseConnector must produce. Documented here
# (not in expenses.md alone) so a future connector author has the contract
# at the import site.
CANONICAL_ACCOUNT_TYPES = ("expense", "cogs", "income", "asset", "liability", "equity", "other")
CANONICAL_BILL_STATUSES = ("open", "partial", "paid", "voided")
CANONICAL_PAYMENT_TYPES = ("cash", "credit_card", "check", "bank_transfer", "other")


class ExpenseConnector(WebhookConnector, ABC):
    """A WebhookConnector that emits expense-side events.

    Subclasses translate native vendor/account/bill/expense vocabulary into
    Tidemill's canonical enums (see CANONICAL_* tuples above). The expense
    schema is platform-neutral — QuickBooks, Xero, FreshBooks, Wave, Sage
    plug in by implementing these four normalize/extract methods plus their
    own auth + entity translation; no schema changes are required.
    """

    @classmethod
    @abstractmethod
    def normalize_account_type(cls, native: str) -> str:
        """Map a native account-type string to one of CANONICAL_ACCOUNT_TYPES."""

    @classmethod
    @abstractmethod
    def normalize_bill_status(cls, native: str) -> str:
        """Map a native bill-status string to one of CANONICAL_BILL_STATUSES."""

    @classmethod
    @abstractmethod
    def normalize_payment_type(cls, native: str) -> str:
        """Map a native payment-type string to one of CANONICAL_PAYMENT_TYPES."""

    @classmethod
    @abstractmethod
    def extract_dimensions(cls, native_obj: dict[str, Any]) -> dict[str, Any]:
        """Pull cross-cutting tagging dimensions (project/class/department) from a line item."""
