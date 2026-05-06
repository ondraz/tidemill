"""QuickBooks Online connector — translates QBO entities into Tidemill events.

QBO is fundamentally an accounting platform, not a billing platform. We use it
purely as an *expense* source: vendors, chart of accounts, bills, purchases,
bill-payments. Subscription/MRR concepts are intentionally absent.

QBO webhooks differ from Stripe's: they only carry change notifications
(``{realmId, name, id, operation}``) — the connector must call the QBO REST API
to fetch the full entity. The route handler awaits ``fetch_and_translate`` for
that reason; ``translate()`` itself returns ``[]`` because the bare notification
payload has no business data.

Account-type and payment-type vocabulary is normalized to the canonical enums
in ``tidemill.connectors.base`` so downstream code (state handlers, metrics)
never sees QBO-specific strings.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from tidemill.connectors.base import ExpenseConnector
from tidemill.connectors.registry import register
from tidemill.events import Event, make_event_id

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import APIRouter


# ── canonical enum mapping tables (QBO native → Tidemill canonical) ──────

# QBO AccountType values — see Intuit docs:
# https://developer.intuit.com/app/developer/qbo/docs/api/accounting/most-commonly-used/account
_QBO_ACCOUNT_TYPE_MAP = {
    "Expense": "expense",
    "Other Expense": "expense",
    "Cost of Goods Sold": "cogs",
    "Income": "income",
    "Other Income": "income",
    "Bank": "asset",
    "Accounts Receivable": "asset",
    "Other Current Asset": "asset",
    "Fixed Asset": "asset",
    "Other Asset": "asset",
    "Accounts Payable": "liability",
    "Credit Card": "liability",
    "Long Term Liability": "liability",
    "Other Current Liability": "liability",
    "Equity": "equity",
}

# QBO Purchase.PaymentType
_QBO_PAYMENT_TYPE_MAP = {
    "Cash": "cash",
    "Check": "check",
    "CreditCard": "credit_card",
}


def _ts(value: str | None) -> datetime | None:
    """Parse a QBO ISO 8601 string, or return None."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _date_to_iso(date_str: str | None) -> str | None:
    """Convert QBO ``YYYY-MM-DD`` (date) to ISO 8601 timestamp at UTC midnight."""
    if not date_str:
        return None
    return f"{date_str}T00:00:00+00:00"


def _to_cents(amount: Any) -> int:
    """QBO uses decimal Amount fields. Convert to integer cents."""
    if amount is None:
        return 0
    return int(round(float(amount) * 100))


@register("quickbooks")
class QuickBooksConnector(ExpenseConnector):
    """QBO webhook + backfill translator."""

    @property
    def source_type(self) -> str:
        return "quickbooks"

    @classmethod
    def router(cls) -> APIRouter:
        from tidemill.connectors.quickbooks.routes import router

        return router

    # ── ExpenseConnector contract ────────────────────────────────────────

    @classmethod
    def normalize_account_type(cls, native: str) -> str:
        return _QBO_ACCOUNT_TYPE_MAP.get(native, "other")

    @classmethod
    def normalize_bill_status(cls, native: str) -> str:
        # QBO bills don't have a single "status" field; the route handler /
        # backfill compute it from Balance vs TotalAmt. Native is one of
        # {open, partial, paid} produced by ``_compute_bill_status``.
        if native in ("open", "partial", "paid", "voided"):
            return native
        return "open"

    @classmethod
    def normalize_payment_type(cls, native: str) -> str:
        return _QBO_PAYMENT_TYPE_MAP.get(native, "other")

    @classmethod
    def extract_dimensions(cls, native_obj: dict[str, Any]) -> dict[str, Any]:
        """Pull QBO Class and Department off a line/header.

        QBO supports Class (cross-cutting tag) and Department (location).
        Both are reference objects with ``{value, name}``; we keep ``value``
        (the QBO ID) so reports can group by stable identifier.
        """
        dims: dict[str, Any] = {}
        cls_ref = native_obj.get("ClassRef")
        if cls_ref:
            dims["class"] = cls_ref.get("name") or cls_ref.get("value")
        dept_ref = native_obj.get("DepartmentRef")
        if dept_ref:
            dims["department"] = dept_ref.get("name") or dept_ref.get("value")
        return dims

    # ── translate / verify_signature ─────────────────────────────────────

    def translate(self, webhook_payload: dict[str, Any]) -> list[Event]:
        """Return ``[]`` — QBO webhook payloads carry no business data.

        The route handler must call :meth:`fetch_and_translate` to fetch
        each referenced entity from the QBO API. Implemented for protocol
        conformance with :class:`WebhookConnector`.
        """
        return []

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """QBO signs webhooks with HMAC-SHA256 over the raw body.

        The verifier-token is set when the webhook is registered in the Intuit
        Developer dashboard. The signature header is base64-encoded.
        """
        verifier_token = self.config.get("webhook_verifier_token")
        if not verifier_token:
            # No verifier configured → accept (matches Stripe's lenient default).
            return True
        import base64

        digest = hmac.new(
            verifier_token.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        return hmac.compare_digest(expected, signature)

    # ── webhook fetch-and-translate ──────────────────────────────────────

    async def fetch_and_translate(self, payload: dict[str, Any]) -> list[Event]:
        """Fetch each referenced entity and translate it into Tidemill events.

        Notification shape (Intuit docs):
            {"eventNotifications": [
                {"realmId": "...",
                 "dataChangeEvent": {"entities": [
                     {"name": "Bill", "id": "123", "operation": "Create",
                      "lastUpdated": "..."}, ...]}}]}
        """
        from tidemill.connectors.quickbooks.client import QuickBooksClient

        events: list[Event] = []
        client = QuickBooksClient(self.config, source_id=self.source_id)
        try:
            for notif in payload.get("eventNotifications", []):
                realm_id = notif.get("realmId", "")
                entities = (notif.get("dataChangeEvent") or {}).get("entities", [])
                for entity in entities:
                    name = entity.get("name", "")
                    qbo_id = entity.get("id", "")
                    op = entity.get("operation", "")
                    if op == "Delete":
                        # QBO deletes are rare for expense entities; emit a
                        # voided event so downstream can react.
                        events.extend(self._build_delete_events(name, qbo_id, realm_id))
                        continue
                    obj = await client.get_entity(realm_id, name, qbo_id)
                    if obj is None:
                        continue
                    events.extend(self._translate_entity(name, obj, realm_id))
        finally:
            await client.close()
        return events

    # ── backfill ─────────────────────────────────────────────────────────

    async def backfill(
        self, since: datetime | None = None
    ) -> AsyncIterator[Event]:  # pragma: no cover — needs a real QBO API
        """Paginate through Vendors → Accounts → Bills → Purchases → BillPayments.

        Order matters: vendors and accounts must exist before bill / expense
        events resolve their FK lookups.
        """
        from tidemill.connectors.quickbooks.client import QuickBooksClient

        realm_id = self.config.get("realm_id", "")
        if not realm_id:
            raise ValueError("quickbooks connector config missing 'realm_id'")
        since_clause = ""
        if since is not None:
            since_clause = f" WHERE Metadata.LastUpdatedTime > '{since.isoformat()}'"

        client = QuickBooksClient(self.config, source_id=self.source_id)
        try:
            # Vendors first so bills/expenses can resolve vendor_id.
            for entity_type in ("Vendor", "Account"):
                async for obj in client.query_entities(realm_id, entity_type, since_clause):
                    for evt in self._translate_entity(entity_type, obj, realm_id):
                        yield evt
            # Then transactional entities.
            for entity_type in ("Bill", "Purchase", "BillPayment"):
                async for obj in client.query_entities(realm_id, entity_type, since_clause):
                    for evt in self._translate_entity(entity_type, obj, realm_id):
                        yield evt
        finally:
            await client.close()

    # ── per-entity translation ───────────────────────────────────────────

    def _translate_entity(
        self, name: str, obj: dict[str, Any], realm_id: str
    ) -> list[Event]:
        match name:
            case "Vendor":
                return [self._translate_vendor(obj, realm_id)]
            case "Account":
                return [self._translate_account(obj, realm_id)]
            case "Bill":
                return self._translate_bill(obj, realm_id)
            case "Purchase":
                return [self._translate_purchase(obj, realm_id)]
            case "BillPayment":
                return [self._translate_bill_payment(obj, realm_id)]
        return []

    def _build_delete_events(
        self, name: str, qbo_id: str, realm_id: str
    ) -> list[Event]:
        match name:
            case "Vendor":
                return [
                    self._make_event(
                        "vendor.deleted",
                        customer_id=realm_id,
                        external_id=qbo_id,
                        occurred_at=datetime.now(UTC),
                        payload={"external_id": qbo_id},
                    )
                ]
            case "Bill":
                return [
                    self._make_event(
                        "bill.voided",
                        customer_id=realm_id,
                        external_id=qbo_id,
                        occurred_at=datetime.now(UTC),
                        payload={
                            "external_id": qbo_id,
                            "voided_at": datetime.now(UTC).isoformat(),
                        },
                    )
                ]
            case "Purchase":
                return [
                    self._make_event(
                        "expense.voided",
                        customer_id=realm_id,
                        external_id=qbo_id,
                        occurred_at=datetime.now(UTC),
                        payload={
                            "external_id": qbo_id,
                            "voided_at": datetime.now(UTC).isoformat(),
                        },
                    )
                ]
        return []

    def _translate_vendor(self, obj: dict[str, Any], realm_id: str) -> Event:
        ext_id = obj["Id"]
        primary_email = (obj.get("PrimaryEmailAddr") or {}).get("Address")
        bill_addr = obj.get("BillAddr") or {}
        return self._make_event(
            "vendor.created",
            customer_id=realm_id,
            external_id=ext_id,
            occurred_at=_ts(obj.get("MetaData", {}).get("CreateTime")) or datetime.now(UTC),
            payload={
                "external_id": ext_id,
                "name": obj.get("DisplayName") or obj.get("CompanyName"),
                "email": primary_email,
                "country": bill_addr.get("Country"),
                "currency": (obj.get("CurrencyRef") or {}).get("value"),
                "active": obj.get("Active", True),
                "metadata": {"native_object": "Vendor", "qbo_id": ext_id},
            },
        )

    def _translate_account(self, obj: dict[str, Any], realm_id: str) -> Event:
        ext_id = obj["Id"]
        native_type = obj.get("AccountType", "")
        parent_ref = obj.get("ParentRef") or {}
        return self._make_event(
            "account.created",
            customer_id=realm_id,
            external_id=ext_id,
            occurred_at=_ts(obj.get("MetaData", {}).get("CreateTime")) or datetime.now(UTC),
            payload={
                "external_id": ext_id,
                "name": obj.get("Name"),
                "account_type": self.normalize_account_type(native_type),
                "account_subtype": obj.get("AccountSubType"),
                "parent_external_id": parent_ref.get("value"),
                "currency": (obj.get("CurrencyRef") or {}).get("value"),
                "active": obj.get("Active", True),
                "metadata": {
                    "native_account_type": native_type,
                    "qbo_id": ext_id,
                },
            },
        )

    @staticmethod
    def _compute_bill_status(obj: dict[str, Any]) -> str:
        """Derive status from Balance / TotalAmt. QBO has no explicit field."""
        total = float(obj.get("TotalAmt", 0) or 0)
        balance = float(obj.get("Balance", total) or 0)
        if balance <= 0:
            return "paid"
        if balance < total:
            return "partial"
        return "open"

    def _translate_bill(self, obj: dict[str, Any], realm_id: str) -> list[Event]:
        ext_id = obj["Id"]
        currency = (obj.get("CurrencyRef") or {}).get("value")
        total_cents = _to_cents(obj.get("TotalAmt"))
        status = self._compute_bill_status(obj)

        lines = []
        for raw_line in obj.get("Line") or []:
            if raw_line.get("DetailType") not in (
                "AccountBasedExpenseLineDetail",
                "ItemBasedExpenseLineDetail",
            ):
                continue
            detail = raw_line.get(raw_line["DetailType"]) or {}
            account_ref = detail.get("AccountRef") or {}
            lines.append(
                {
                    "account_external_id": account_ref.get("value"),
                    "description": raw_line.get("Description"),
                    "amount_cents": _to_cents(raw_line.get("Amount")),
                    "currency": currency,
                    "dimensions": self.extract_dimensions(detail),
                }
            )

        events: list[Event] = []
        events.append(
            self._make_event(
                "bill.created",
                customer_id=realm_id,
                external_id=ext_id,
                occurred_at=_ts(_date_to_iso(obj.get("TxnDate"))) or datetime.now(UTC),
                payload={
                    "external_id": ext_id,
                    "vendor_external_id": (obj.get("VendorRef") or {}).get("value"),
                    "status": status,
                    "doc_number": obj.get("DocNumber"),
                    "currency": currency,
                    "subtotal_cents": total_cents,
                    "tax_cents": _to_cents((obj.get("TxnTaxDetail") or {}).get("TotalTax")),
                    "total_cents": total_cents,
                    "txn_date": _date_to_iso(obj.get("TxnDate")),
                    "due_date": _date_to_iso(obj.get("DueDate")),
                    "memo": obj.get("PrivateNote"),
                    "lines": lines,
                    "metadata": {"qbo_id": ext_id},
                },
            )
        )
        if status == "paid":
            events.append(
                self._make_event(
                    "bill.paid",
                    customer_id=realm_id,
                    external_id=ext_id,
                    occurred_at=datetime.now(UTC),
                    payload={"external_id": ext_id, "paid_at": datetime.now(UTC).isoformat()},
                )
            )
        return events

    def _translate_purchase(self, obj: dict[str, Any], realm_id: str) -> Event:
        """QBO ``Purchase`` = direct cash/credit/check expense (no bill)."""
        ext_id = obj["Id"]
        currency = (obj.get("CurrencyRef") or {}).get("value")
        total_cents = _to_cents(obj.get("TotalAmt"))

        lines = []
        for raw_line in obj.get("Line") or []:
            if raw_line.get("DetailType") not in (
                "AccountBasedExpenseLineDetail",
                "ItemBasedExpenseLineDetail",
            ):
                continue
            detail = raw_line.get(raw_line["DetailType"]) or {}
            account_ref = detail.get("AccountRef") or {}
            lines.append(
                {
                    "account_external_id": account_ref.get("value"),
                    "description": raw_line.get("Description"),
                    "amount_cents": _to_cents(raw_line.get("Amount")),
                    "currency": currency,
                    "dimensions": self.extract_dimensions(detail),
                }
            )

        # Purchase counterparty can be Vendor, Customer, or Employee. We only
        # link Vendor — others get null vendor_id.
        entity_ref = obj.get("EntityRef") or {}
        vendor_ext_id = entity_ref.get("value") if entity_ref.get("type") == "Vendor" else None

        return self._make_event(
            "expense.created",
            customer_id=realm_id,
            external_id=ext_id,
            occurred_at=_ts(_date_to_iso(obj.get("TxnDate"))) or datetime.now(UTC),
            payload={
                "external_id": ext_id,
                "vendor_external_id": vendor_ext_id,
                "payment_type": self.normalize_payment_type(obj.get("PaymentType", "")),
                "doc_number": obj.get("DocNumber"),
                "currency": currency,
                "subtotal_cents": total_cents,
                "tax_cents": _to_cents((obj.get("TxnTaxDetail") or {}).get("TotalTax")),
                "total_cents": total_cents,
                "txn_date": _date_to_iso(obj.get("TxnDate")),
                "memo": obj.get("PrivateNote"),
                "lines": lines,
                "metadata": {"qbo_id": ext_id, "native_payment_type": obj.get("PaymentType")},
            },
        )

    def _translate_bill_payment(self, obj: dict[str, Any], realm_id: str) -> Event:
        ext_id = obj["Id"]
        # A BillPayment can apply to multiple bills via Line[].LinkedTxn —
        # we pick the first linked Bill for simplicity. Connectors that need
        # full split attribution can extend this later.
        bill_ext_id: str | None = None
        for raw_line in obj.get("Line") or []:
            for linked in raw_line.get("LinkedTxn") or []:
                if linked.get("TxnType") == "Bill":
                    bill_ext_id = linked.get("TxnId")
                    break
            if bill_ext_id:
                break
        return self._make_event(
            "bill_payment.created",
            customer_id=realm_id,
            external_id=ext_id,
            occurred_at=_ts(_date_to_iso(obj.get("TxnDate"))) or datetime.now(UTC),
            payload={
                "external_id": ext_id,
                "bill_external_id": bill_ext_id or "",
                "paid_at": _date_to_iso(obj.get("TxnDate")),
                "amount_cents": _to_cents(obj.get("TotalAmt")),
                "currency": (obj.get("CurrencyRef") or {}).get("value"),
                "metadata": {"qbo_id": ext_id},
            },
        )

    # ── event factory ────────────────────────────────────────────────────

    def _make_event(
        self,
        event_type: str,
        *,
        customer_id: str,
        external_id: str,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> Event:
        return Event(
            id=make_event_id(self.source_id, event_type, external_id),
            source_id=self.source_id,
            type=event_type,
            occurred_at=occurred_at,
            published_at=datetime.now(UTC),
            customer_id=customer_id,
            payload=payload,
        )
