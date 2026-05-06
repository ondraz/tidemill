"""Tests for the QuickBooks Online connector.

Covers translate logic, signature verification, and canonical-enum mapping.
All pure-Python, no DB or network.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from tidemill.connectors.quickbooks import QuickBooksConnector

SRC = "quickbooks-test"


@pytest.fixture
def connector() -> QuickBooksConnector:
    return QuickBooksConnector(source_id=SRC, config={"webhook_verifier_token": "secret"})


# ── canonical enum mapping ───────────────────────────────────────────────


class TestNormalizeAccountType:
    def test_expense_maps_to_expense(self):
        assert QuickBooksConnector.normalize_account_type("Expense") == "expense"

    def test_other_expense_also_maps_to_expense(self):
        assert QuickBooksConnector.normalize_account_type("Other Expense") == "expense"

    def test_cogs(self):
        assert QuickBooksConnector.normalize_account_type("Cost of Goods Sold") == "cogs"

    def test_income(self):
        assert QuickBooksConnector.normalize_account_type("Income") == "income"

    def test_bank_is_asset(self):
        assert QuickBooksConnector.normalize_account_type("Bank") == "asset"

    def test_credit_card_is_liability(self):
        assert QuickBooksConnector.normalize_account_type("Credit Card") == "liability"

    def test_equity(self):
        assert QuickBooksConnector.normalize_account_type("Equity") == "equity"

    def test_unknown_falls_back_to_other(self):
        assert QuickBooksConnector.normalize_account_type("WeirdNewType") == "other"


class TestNormalizePaymentType:
    def test_cash(self):
        assert QuickBooksConnector.normalize_payment_type("Cash") == "cash"

    def test_check(self):
        assert QuickBooksConnector.normalize_payment_type("Check") == "check"

    def test_credit_card(self):
        assert QuickBooksConnector.normalize_payment_type("CreditCard") == "credit_card"

    def test_unknown_falls_back_to_other(self):
        assert QuickBooksConnector.normalize_payment_type("Bitcoin") == "other"


class TestExtractDimensions:
    def test_no_class_or_department(self):
        assert QuickBooksConnector.extract_dimensions({}) == {}

    def test_class_ref(self):
        line = {"ClassRef": {"value": "1", "name": "Engineering"}}
        assert QuickBooksConnector.extract_dimensions(line) == {"class": "Engineering"}

    def test_department_ref(self):
        line = {"DepartmentRef": {"value": "10", "name": "EMEA"}}
        assert QuickBooksConnector.extract_dimensions(line) == {"department": "EMEA"}

    def test_both(self):
        line = {
            "ClassRef": {"value": "1", "name": "Eng"},
            "DepartmentRef": {"value": "10", "name": "EMEA"},
        }
        assert QuickBooksConnector.extract_dimensions(line) == {
            "class": "Eng",
            "department": "EMEA",
        }


# ── signature verification ───────────────────────────────────────────────


class TestSignatureVerification:
    def test_valid_signature(self, connector: QuickBooksConnector):
        body = b'{"eventNotifications": []}'
        digest = hmac.new(b"secret", body, hashlib.sha256).digest()
        sig = base64.b64encode(digest).decode()
        assert connector.verify_signature(body, sig) is True

    def test_invalid_signature(self, connector: QuickBooksConnector):
        body = b'{"eventNotifications": []}'
        assert connector.verify_signature(body, "wrong-sig") is False

    def test_no_verifier_configured_accepts(self):
        c = QuickBooksConnector(source_id=SRC, config={})
        assert c.verify_signature(b"anything", "any-sig") is True


# ── translate (full QBO entity payloads) ─────────────────────────────────


_VENDOR_PAYLOAD = {
    "Id": "42",
    "DisplayName": "Acme Corp",
    "PrimaryEmailAddr": {"Address": "ap@acme.example"},
    "BillAddr": {"Country": "US"},
    "CurrencyRef": {"value": "USD"},
    "Active": True,
    "MetaData": {"CreateTime": "2025-01-15T12:00:00-08:00"},
}


_ACCOUNT_PAYLOAD = {
    "Id": "100",
    "Name": "AWS Hosting",
    "AccountType": "Expense",
    "AccountSubType": "UtilitiesPayable",
    "Active": True,
    "MetaData": {"CreateTime": "2025-01-15T12:00:00-08:00"},
}


_BILL_PAYLOAD = {
    "Id": "555",
    "VendorRef": {"value": "42"},
    "TxnDate": "2026-01-15",
    "DueDate": "2026-02-14",
    "DocNumber": "INV-001",
    "TotalAmt": 4200.00,
    "Balance": 4200.00,
    "CurrencyRef": {"value": "USD"},
    "Line": [
        {
            "Amount": 4200.00,
            "Description": "AWS hosting Jan",
            "DetailType": "AccountBasedExpenseLineDetail",
            "AccountBasedExpenseLineDetail": {
                "AccountRef": {"value": "100"},
                "ClassRef": {"value": "1", "name": "Engineering"},
            },
        }
    ],
    "PrivateNote": "Monthly hosting bill",
}


_PURCHASE_PAYLOAD = {
    "Id": "777",
    "EntityRef": {"value": "42", "type": "Vendor"},
    "PaymentType": "CreditCard",
    "TxnDate": "2026-02-10",
    "TotalAmt": 320.00,
    "CurrencyRef": {"value": "USD"},
    "Line": [
        {
            "Amount": 320.00,
            "Description": "Standing desk",
            "DetailType": "AccountBasedExpenseLineDetail",
            "AccountBasedExpenseLineDetail": {"AccountRef": {"value": "200"}},
        }
    ],
}


_BILL_PAYMENT_PAYLOAD = {
    "Id": "999",
    "VendorRef": {"value": "42"},
    "TxnDate": "2026-02-01",
    "TotalAmt": 4200.00,
    "CurrencyRef": {"value": "USD"},
    "Line": [
        {
            "Amount": 4200.00,
            "LinkedTxn": [{"TxnId": "555", "TxnType": "Bill"}],
        }
    ],
}


REALM = "realm-1"


class TestTranslateVendor:
    def test_emits_vendor_created(self, connector: QuickBooksConnector):
        events = connector._translate_entity("Vendor", _VENDOR_PAYLOAD, REALM)
        assert len(events) == 1
        evt = events[0]
        assert evt.type == "vendor.created"
        assert evt.source_id == SRC
        assert evt.customer_id == REALM  # realmId carries through customer_id slot
        assert evt.payload["external_id"] == "42"
        assert evt.payload["name"] == "Acme Corp"
        assert evt.payload["email"] == "ap@acme.example"
        assert evt.payload["country"] == "US"
        assert evt.payload["currency"] == "USD"

    def test_id_is_idempotent(self, connector: QuickBooksConnector):
        e1 = connector._translate_entity("Vendor", _VENDOR_PAYLOAD, REALM)[0]
        e2 = connector._translate_entity("Vendor", _VENDOR_PAYLOAD, REALM)[0]
        assert e1.id == e2.id


class TestTranslateAccount:
    def test_emits_account_created_with_normalized_type(
        self, connector: QuickBooksConnector
    ):
        events = connector._translate_entity("Account", _ACCOUNT_PAYLOAD, REALM)
        assert len(events) == 1
        evt = events[0]
        assert evt.type == "account.created"
        assert evt.payload["external_id"] == "100"
        # Normalized to canonical 'expense'
        assert evt.payload["account_type"] == "expense"
        # Native preserved in metadata
        assert evt.payload["metadata"]["native_account_type"] == "Expense"
        assert evt.payload["account_subtype"] == "UtilitiesPayable"


class TestTranslateBill:
    def test_emits_bill_created(self, connector: QuickBooksConnector):
        events = connector._translate_entity("Bill", _BILL_PAYLOAD, REALM)
        # Open bill → only bill.created (no bill.paid emitted)
        assert len(events) == 1
        evt = events[0]
        assert evt.type == "bill.created"
        assert evt.payload["external_id"] == "555"
        assert evt.payload["vendor_external_id"] == "42"
        assert evt.payload["status"] == "open"
        assert evt.payload["doc_number"] == "INV-001"
        assert evt.payload["currency"] == "USD"
        assert evt.payload["total_cents"] == 420000
        # Lines preserved with account ref + dimensions
        assert len(evt.payload["lines"]) == 1
        line = evt.payload["lines"][0]
        assert line["account_external_id"] == "100"
        assert line["amount_cents"] == 420000
        assert line["dimensions"] == {"class": "Engineering"}

    def test_paid_bill_emits_two_events(self, connector: QuickBooksConnector):
        paid_payload = dict(_BILL_PAYLOAD)
        paid_payload["Balance"] = 0.0
        events = connector._translate_entity("Bill", paid_payload, REALM)
        types = [e.type for e in events]
        assert "bill.created" in types
        assert "bill.paid" in types

    def test_partial_status_when_balance_below_total(
        self, connector: QuickBooksConnector
    ):
        partial_payload = dict(_BILL_PAYLOAD)
        partial_payload["Balance"] = 2000.00
        events = connector._translate_entity("Bill", partial_payload, REALM)
        assert events[0].payload["status"] == "partial"


class TestTranslatePurchase:
    def test_emits_expense_created_with_canonical_payment_type(
        self, connector: QuickBooksConnector
    ):
        events = connector._translate_entity("Purchase", _PURCHASE_PAYLOAD, REALM)
        assert len(events) == 1
        evt = events[0]
        assert evt.type == "expense.created"
        assert evt.payload["external_id"] == "777"
        assert evt.payload["vendor_external_id"] == "42"
        # Native CreditCard normalized to credit_card
        assert evt.payload["payment_type"] == "credit_card"
        assert evt.payload["total_cents"] == 32000
        assert evt.payload["lines"][0]["amount_cents"] == 32000

    def test_non_vendor_entity_drops_vendor_link(
        self, connector: QuickBooksConnector
    ):
        payload = dict(_PURCHASE_PAYLOAD)
        payload["EntityRef"] = {"value": "99", "type": "Customer"}
        events = connector._translate_entity("Purchase", payload, REALM)
        assert events[0].payload["vendor_external_id"] is None


class TestTranslateBillPayment:
    def test_links_to_bill(self, connector: QuickBooksConnector):
        events = connector._translate_entity(
            "BillPayment", _BILL_PAYMENT_PAYLOAD, REALM
        )
        assert len(events) == 1
        evt = events[0]
        assert evt.type == "bill_payment.created"
        assert evt.payload["external_id"] == "999"
        assert evt.payload["bill_external_id"] == "555"
        assert evt.payload["amount_cents"] == 420000


# ── translate() entry point — QBO webhook payloads carry no body ─────────


def test_translate_returns_empty_list(connector: QuickBooksConnector):
    """Verify ``translate()`` is a no-op for QBO notifications.

    QBO notifications carry only entity IDs; the route handler must call
    ``fetch_and_translate`` to retrieve the full entity from the API.
    """
    payload = {
        "eventNotifications": [
            {
                "realmId": REALM,
                "dataChangeEvent": {
                    "entities": [{"name": "Bill", "id": "1", "operation": "Create"}]
                },
            }
        ]
    }
    assert connector.translate(payload) == []
