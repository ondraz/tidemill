"""Connector base classes and the canonical vocabulary every connector emits.

A connector's job is to translate provider-specific shapes (Stripe webhook
payloads, Chargebee REST objects, QBO entity dumps) into Tidemill's canonical
event shape so the rest of the system never sees provider-specific strings.

The canonical enum tuples below are the contract: connectors must map their
native vocabulary onto these values, and the state layer rejects anything
else via :func:`validate_canonical` (routing the offending event to the
dead-letter queue rather than corrupting analytics).

See ``docs/architecture/canonical-vocabulary.md`` for the per-provider
mapping tables.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from datetime import date, datetime

    from fastapi import APIRouter
    from sqlalchemy.ext.asyncio import AsyncEngine

    from tidemill.events import Event


# ── Canonical enums (billing side) ───────────────────────────────────────
# Mirrors the expense-side CANONICAL_* tuples below. Documented in
# canonical-vocabulary.md with provider mappings.

CANONICAL_INTERVALS = ("day", "week", "month", "year")
CANONICAL_PRICING_MODELS = ("flat", "tiered", "volume", "usage_based")
CANONICAL_USAGE_TYPES = ("licensed", "metered")
CANONICAL_SUBSCRIPTION_STATUSES = (
    "active",
    "trialing",
    "pending_payment",
    "paused",
    "canceled",
)
CANONICAL_INVOICE_STATUSES = ("draft", "open", "paid", "void", "uncollectible")
CANONICAL_LINE_ITEM_KINDS = (
    "subscription",
    "usage",
    "addon",
    "proration",
    "tax",
    "discount",
    "credit",
    "other",
)
CANONICAL_PAYMENT_STATUSES = ("pending", "succeeded", "failed", "refunded")
CANONICAL_PAYMENT_METHOD_TYPES = (
    "card",
    "bank_transfer",
    "direct_debit",
    "wallet",
    "paypal",
    "other",
)

# ── Canonical enums (expense side) ───────────────────────────────────────
# Pre-existing; preserved verbatim for the QuickBooks connector contract.

CANONICAL_ACCOUNT_TYPES = ("expense", "cogs", "income", "asset", "liability", "equity", "other")
CANONICAL_BILL_STATUSES = ("open", "partial", "paid", "voided")
CANONICAL_PAYMENT_TYPES = ("cash", "credit_card", "check", "bank_transfer", "other")


class CanonicalEnumViolation(ValueError):
    """A connector emitted a value outside the canonical set for *field*.

    Raised from :func:`validate_canonical` and caught by the worker, which
    routes the offending event to ``dead_letter_event`` with
    ``error_type='canonical_enum_violation'`` — the bad value never reaches
    a core table.
    """

    def __init__(self, field: str, value: Any, allowed: tuple[str, ...]) -> None:
        self.field = field
        self.value = value
        self.allowed = allowed
        super().__init__(f"{field}={value!r} is not one of the canonical values {allowed}")


def validate_canonical(
    value: str | None,
    allowed: tuple[str, ...],
    field: str,
) -> str | None:
    """Return *value* unchanged when canonical, else raise.

    ``None`` is always passed through — a connector that omits an optional
    canonical field is legal; the state layer treats it as "unknown" rather
    than corrupting analytics. Only writes of a *non-canonical* string raise.
    """
    if value is None or value in allowed:
        return value
    raise CanonicalEnumViolation(field, value, allowed)


def compute_mrr_cents(
    amount_cents: int | None,
    interval: str | None,
    interval_count: int | None = 1,
    quantity: int = 1,
) -> int:
    """Normalize a recurring charge to monthly cents.

    Operates on canonical fields, so any connector (Stripe, Chargebee,
    Recurly, Lago, …) can call it after mapping its native plan shape onto
    ``interval`` ∈ :data:`CANONICAL_INTERVALS` and ``amount_cents`` in the
    plan's own currency.

    Connectors whose source already exposes MRR server-side (Chargebee's
    ``subscription.mrr``, Recurly's billing summary) may skip this and
    populate ``mrr_cents`` directly on the event payload — the state layer
    honors connector-provided MRR verbatim.

    Day and week intervals are scaled by 365/12 and 52/12 respectively so
    the result is comparable across pricing models. Anything else returns 0
    rather than raising; the connector is expected to have validated the
    interval against :func:`validate_canonical` first.
    """
    if not amount_cents or not interval:
        return 0
    ic = interval_count or 1
    qty = quantity or 1
    amount = amount_cents * qty
    match interval:
        case "month":
            return amount // ic
        case "year":
            return amount // (12 * ic)
        case "week":
            return int(amount * 52 / (12 * ic))
        case "day":
            return int(amount * 365 / (12 * ic))
    return 0


# ── Connector base classes ───────────────────────────────────────────────


class WebhookConnector(ABC):
    """Translates billing-system webhooks into internal canonical events."""

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
    rather than ingesting events. See ``docs/architecture/connectors.md``.

    Subclasses return canonical-shaped rows (``status`` ∈
    :data:`CANONICAL_SUBSCRIPTION_STATUSES`, etc.) so metric queries never
    see provider-specific vocabulary.
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

    @abstractmethod
    async def get_mrr_cents(self, at: date | None = None) -> int:
        """Total MRR in cents (original currency) at *at*."""

    @abstractmethod
    async def get_subscription_changes(self, start: date, end: date) -> list[dict[str, Any]]:
        """Subscription state changes in ``[start, end]`` (closed-closed).

        Each change should include: ``type`` (one of ``new`` / ``expansion`` /
        ``contraction`` / ``churn`` / ``reactivation``), ``amount_cents``,
        ``currency``, ``customer_external_id``, ``subscription_external_id``,
        ``occurred_at``.
        """

    @abstractmethod
    async def get_customers(self, at: date | None = None) -> list[dict[str, Any]]:
        """Customer records as of *at*."""

    @abstractmethod
    async def get_invoices(self, start: date, end: date) -> list[dict[str, Any]]:
        """Invoices issued in ``[start, end]`` (closed-closed)."""


class ExpenseConnector(WebhookConnector, ABC):
    """A WebhookConnector that emits expense-side events.

    Subclasses translate native vendor/account/bill/expense vocabulary into
    Tidemill's canonical enums (see CANONICAL_ACCOUNT_TYPES /
    CANONICAL_BILL_STATUSES / CANONICAL_PAYMENT_TYPES). The expense schema
    is platform-neutral — QuickBooks, Xero, FreshBooks, Wave, Sage plug in
    by implementing these four normalize/extract methods plus their own
    auth + entity translation; no schema changes are required.
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
