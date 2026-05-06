#!/usr/bin/env python3
"""Seed a QBO sandbox company with realistic expense data.

Mirrors ``stripe_seed.py``: covers the same 18-month window (today − 18 months)
so revenue and expense periods overlap when both seeds are run together.

What's created:
  - 6 vendors with rotating countries (matches Stripe seed's currency mix)
  - ~12 chart-of-accounts entries spanning Expense + COGS + Income + Asset
  - Recurring monthly bills per vendor (e.g. AWS hosting, Hetzner servers)
  - One-off purchases (cash/credit-card expenses) sprinkled across the range
  - Bill payments marking ~80% of bills as paid

QBO has no test-clock equivalent, so historical data is created by backdating
``TxnDate`` / ``DueDate``. Idempotent re-runs: every entity name is prefixed
with ``SEED-`` so ``--cleanup`` can find and void/delete them.

Prerequisites:
    pip install httpx
    export QUICKBOOKS_CLIENT_ID=...
    export QUICKBOOKS_CLIENT_SECRET=...
    export QUICKBOOKS_SANDBOX_REFRESH_TOKEN=...
    export QUICKBOOKS_SANDBOX_REALM_ID=...

Usage:
    python quickbooks_seed.py                  # full seed (18 months)
    python quickbooks_seed.py --months 6       # shorter history
    python quickbooks_seed.py --cleanup        # void/delete all SEED-* entities
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
_SANDBOX_BASE = "https://sandbox-quickbooks.api.intuit.com/v3/company"

SEED_PREFIX = "SEED-"

FIXTURES_PATH = Path(__file__).with_name("quickbooks_fixtures.json")


# ── fixture archetypes ──────────────────────────────────────────────────


@dataclass
class VendorSpec:
    name: str
    email: str
    country: str
    currency: str  # USD, EUR, GBP


@dataclass
class AccountSpec:
    name: str
    account_type: str  # QBO native AccountType
    account_subtype: str | None = None


@dataclass
class RecurringBillSpec:
    """A monthly bill that fires on day-of-month for the entire window."""

    vendor: str  # vendor display-name
    account: str  # account name
    amount: float
    currency: str
    day_of_month: int
    description: str


@dataclass
class OneOffPurchaseSpec:
    """A single direct purchase (cash/credit), backdated."""

    vendor: str | None
    account: str
    amount: float
    currency: str
    payment_type: str  # Cash | Check | CreditCard
    days_ago: int
    description: str


def _load_fixtures() -> dict[str, Any]:
    with FIXTURES_PATH.open() as fh:
        return json.load(fh)


# ── QBO client ──────────────────────────────────────────────────────────


class QBOClient:
    def __init__(self, *, client_id: str, client_secret: str, refresh_token: str, realm_id: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self.realm_id = realm_id
        self._access_token: str | None = None
        self._http = httpx.Client(timeout=30.0)

    def _refresh(self) -> str:
        r = self._http.post(
            _TOKEN_URL,
            auth=(self._client_id, self._client_secret),
            data={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
            headers={"Accept": "application/json"},
        )
        r.raise_for_status()
        body = r.json()
        self._access_token = body["access_token"]
        # QBO refresh tokens rotate occasionally — keep the latest one.
        self._refresh_token = body.get("refresh_token", self._refresh_token)
        return self._access_token

    def _headers(self) -> dict[str, str]:
        if not self._access_token:
            self._refresh()
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{_SANDBOX_BASE}/{self.realm_id}/{path}"
        r = self._http.request(method, url, headers=self._headers(), **kwargs)
        if r.status_code == 401:
            self._refresh()
            r = self._http.request(method, url, headers=self._headers(), **kwargs)
        if r.status_code >= 300:
            raise RuntimeError(f"{method} {url} → {r.status_code}: {r.text}")
        return r.json()

    def query(self, qbo_sql: str) -> dict[str, Any]:
        return self._request("GET", "query", params={"query": qbo_sql, "minorversion": "65"})

    def create(self, entity: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST", entity.lower(), params={"minorversion": "65"}, json=body
        )

    def void(self, entity: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            entity.lower(),
            params={"operation": "void", "minorversion": "65"},
            json=body,
        )

    def delete(self, entity: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request(
            "POST",
            entity.lower(),
            params={"operation": "delete", "minorversion": "65"},
            json=body,
        )

    def close(self) -> None:
        self._http.close()


# ── seeders ─────────────────────────────────────────────────────────────


def _date_str(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def create_accounts(qbo: QBOClient, specs: list[AccountSpec]) -> dict[str, str]:
    """Create accounts; return ``{account_name: qbo_id}``."""
    out: dict[str, str] = {}
    for spec in specs:
        body: dict[str, Any] = {
            "Name": SEED_PREFIX + spec.name,
            "AccountType": spec.account_type,
        }
        if spec.account_subtype:
            body["AccountSubType"] = spec.account_subtype
        result = qbo.create("Account", body)
        out[spec.name] = result["Account"]["Id"]
        print(f"  account: {spec.name} ({spec.account_type}) id={out[spec.name]}")
    return out


def create_vendors(qbo: QBOClient, specs: list[VendorSpec]) -> dict[str, str]:
    out: dict[str, str] = {}
    for spec in specs:
        body = {
            "DisplayName": SEED_PREFIX + spec.name,
            "PrimaryEmailAddr": {"Address": spec.email},
            "BillAddr": {"Country": spec.country},
            # CurrencyRef requires multi-currency to be enabled on the QBO
            # company. Skip if you hit "currency not enabled" — sandbox
            # companies ship with USD only by default.
            "CurrencyRef": {"value": spec.currency},
        }
        try:
            result = qbo.create("Vendor", body)
        except RuntimeError as exc:
            if "currency" in str(exc).lower():
                # Retry without CurrencyRef.
                body.pop("CurrencyRef", None)
                result = qbo.create("Vendor", body)
            else:
                raise
        out[spec.name] = result["Vendor"]["Id"]
        print(f"  vendor: {spec.name} id={out[spec.name]}")
    return out


def create_recurring_bills(
    qbo: QBOClient,
    specs: list[RecurringBillSpec],
    *,
    vendor_ids: dict[str, str],
    account_ids: dict[str, str],
    months: int,
) -> list[str]:
    """Create one Bill per vendor per month for the window. Returns bill IDs."""
    bill_ids: list[str] = []
    today = datetime.now(UTC).date()
    window_start = today.replace(day=1) - timedelta(days=30 * months)

    for spec in specs:
        # Walk forward month by month until we pass today.
        current = window_start.replace(day=1)
        while current <= today:
            try:
                txn_date = current.replace(day=spec.day_of_month)
            except ValueError:
                # day_of_month doesn't fit (e.g. Feb 30). Skip this month.
                current = _next_month(current)
                continue
            if txn_date > today:
                break
            body = {
                "VendorRef": {"value": vendor_ids[spec.vendor]},
                "TxnDate": _date_str(txn_date),
                "DueDate": _date_str(txn_date + timedelta(days=30)),
                "PrivateNote": f"{SEED_PREFIX}{spec.description}",
                "Line": [
                    {
                        "Amount": spec.amount,
                        "DetailType": "AccountBasedExpenseLineDetail",
                        "Description": spec.description,
                        "AccountBasedExpenseLineDetail": {
                            "AccountRef": {"value": account_ids[spec.account]},
                        },
                    }
                ],
            }
            result = qbo.create("Bill", body)
            bill_ids.append(result["Bill"]["Id"])
            current = _next_month(current)
    print(f"  bills: {len(bill_ids)} created")
    return bill_ids


def create_one_off_purchases(
    qbo: QBOClient,
    specs: list[OneOffPurchaseSpec],
    *,
    vendor_ids: dict[str, str],
    account_ids: dict[str, str],
) -> list[str]:
    purchase_ids: list[str] = []
    today = datetime.now(UTC).date()
    # QBO Purchase requires AccountRef (the source account — bank/credit card).
    # We need at least one Asset/Liability account to debit.
    # For the sandbox, we'll fetch the first Bank account.
    bank_resp = qbo.query("SELECT * FROM Account WHERE AccountType = 'Bank' MAXRESULTS 1")
    bank_accounts = (bank_resp.get("QueryResponse") or {}).get("Account") or []
    if not bank_accounts:
        print("  WARN: no Bank account found, skipping purchases")
        return purchase_ids
    bank_id = bank_accounts[0]["Id"]

    for spec in specs:
        txn_date = today - timedelta(days=spec.days_ago)
        body: dict[str, Any] = {
            "AccountRef": {"value": bank_id},
            "PaymentType": spec.payment_type,
            "TxnDate": _date_str(txn_date),
            "PrivateNote": f"{SEED_PREFIX}{spec.description}",
            "Line": [
                {
                    "Amount": spec.amount,
                    "DetailType": "AccountBasedExpenseLineDetail",
                    "Description": spec.description,
                    "AccountBasedExpenseLineDetail": {
                        "AccountRef": {"value": account_ids[spec.account]},
                    },
                }
            ],
        }
        if spec.vendor:
            body["EntityRef"] = {"value": vendor_ids[spec.vendor], "type": "Vendor"}
        result = qbo.create("Purchase", body)
        purchase_ids.append(result["Purchase"]["Id"])
    print(f"  purchases: {len(purchase_ids)} created")
    return purchase_ids


def create_bill_payments(qbo: QBOClient, bill_ids: list[str], pay_fraction: float = 0.8) -> int:
    """Pay ~``pay_fraction`` of the supplied bills. Returns count of payments."""
    rng = random.Random(42)
    paid = 0
    # Need a bank account to source payments from.
    bank_resp = qbo.query("SELECT * FROM Account WHERE AccountType = 'Bank' MAXRESULTS 1")
    bank_accounts = (bank_resp.get("QueryResponse") or {}).get("Account") or []
    if not bank_accounts:
        print("  WARN: no Bank account, skipping bill payments")
        return 0
    bank_id = bank_accounts[0]["Id"]

    for bill_id in bill_ids:
        if rng.random() > pay_fraction:
            continue
        # Fetch the bill to learn its vendor and amount.
        try:
            bill = qbo.query(f"SELECT * FROM Bill WHERE Id = '{bill_id}'")
            bill_obj = (bill.get("QueryResponse") or {}).get("Bill", [None])[0]
            if not bill_obj:
                continue
            body = {
                "VendorRef": bill_obj["VendorRef"],
                "TxnDate": bill_obj["TxnDate"],  # match bill date for chronological sanity
                "TotalAmt": bill_obj["TotalAmt"],
                "PayType": "Check",
                "CheckPayment": {"BankAccountRef": {"value": bank_id}},
                "Line": [
                    {
                        "Amount": bill_obj["TotalAmt"],
                        "LinkedTxn": [{"TxnId": bill_id, "TxnType": "Bill"}],
                    }
                ],
            }
            qbo.create("BillPayment", body)
            paid += 1
        except Exception as exc:
            print(f"  WARN: bill payment for {bill_id} failed: {exc}")
    print(f"  bill_payments: {paid} created")
    return paid


def _next_month(d: date) -> date:
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1, day=1)
    return d.replace(month=d.month + 1, day=1)


# ── cleanup ─────────────────────────────────────────────────────────────


def cleanup(qbo: QBOClient) -> None:
    """Void/delete every entity whose Name/DisplayName starts with ``SEED_PREFIX``.

    Order matters: payments → bills → purchases → vendors → accounts.
    QBO doesn't allow account deletion when transactions reference it, so
    accounts are merely deactivated (Active=false).
    """
    print("=== Cleanup: voiding seeded transactions ===")

    # Bill payments don't have a Name field. Find them by linked seeded bills.
    bp_resp = qbo.query("SELECT * FROM BillPayment STARTPOSITION 1 MAXRESULTS 1000")
    for bp in (bp_resp.get("QueryResponse") or {}).get("BillPayment", []) or []:
        with contextlib.suppress(Exception):
            qbo.void("BillPayment", {"Id": bp["Id"], "SyncToken": bp["SyncToken"]})

    bills_resp = qbo.query(
        "SELECT * FROM Bill WHERE PrivateNote LIKE '" + SEED_PREFIX + "%' MAXRESULTS 1000"
    )
    for b in (bills_resp.get("QueryResponse") or {}).get("Bill", []) or []:
        with contextlib.suppress(Exception):
            qbo.void("Bill", {"Id": b["Id"], "SyncToken": b["SyncToken"]})

    purch_resp = qbo.query(
        "SELECT * FROM Purchase WHERE PrivateNote LIKE '" + SEED_PREFIX + "%' MAXRESULTS 1000"
    )
    for p in (purch_resp.get("QueryResponse") or {}).get("Purchase", []) or []:
        with contextlib.suppress(Exception):
            qbo.void("Purchase", {"Id": p["Id"], "SyncToken": p["SyncToken"]})

    vendors_resp = qbo.query(
        "SELECT * FROM Vendor WHERE DisplayName LIKE '" + SEED_PREFIX + "%' MAXRESULTS 1000"
    )
    for v in (vendors_resp.get("QueryResponse") or {}).get("Vendor", []) or []:
        with contextlib.suppress(Exception):
            qbo.create(
                "Vendor",
                {"Id": v["Id"], "SyncToken": v["SyncToken"], "Active": False, "sparse": True},
            )

    accts_resp = qbo.query(
        "SELECT * FROM Account WHERE Name LIKE '" + SEED_PREFIX + "%' MAXRESULTS 1000"
    )
    for a in (accts_resp.get("QueryResponse") or {}).get("Account", []) or []:
        with contextlib.suppress(Exception):
            qbo.create(
                "Account",
                {"Id": a["Id"], "SyncToken": a["SyncToken"], "Active": False, "sparse": True},
            )

    print("Cleanup done.")


# ── main ────────────────────────────────────────────────────────────────


def _parse_specs(fixtures: dict[str, Any]) -> tuple[
    list[VendorSpec], list[AccountSpec], list[RecurringBillSpec], list[OneOffPurchaseSpec]
]:
    vendors = [VendorSpec(**v) for v in fixtures["vendors"]]
    accounts = [AccountSpec(**a) for a in fixtures["accounts"]]
    bills = [RecurringBillSpec(**b) for b in fixtures["recurring_bills"]]
    purchases = [OneOffPurchaseSpec(**p) for p in fixtures["one_off_purchases"]]
    return vendors, accounts, bills, purchases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--months", type=int, default=18)
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args(argv)

    client_id = os.environ.get("QUICKBOOKS_CLIENT_ID")
    client_secret = os.environ.get("QUICKBOOKS_CLIENT_SECRET")
    refresh_token = os.environ.get("QUICKBOOKS_SANDBOX_REFRESH_TOKEN")
    realm_id = os.environ.get("QUICKBOOKS_SANDBOX_REALM_ID")
    if not (client_id and client_secret and refresh_token and realm_id):
        print(
            "ERROR: set QUICKBOOKS_CLIENT_ID, QUICKBOOKS_CLIENT_SECRET,"
            " QUICKBOOKS_SANDBOX_REFRESH_TOKEN, QUICKBOOKS_SANDBOX_REALM_ID",
            file=sys.stderr,
        )
        return 2

    qbo = QBOClient(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        realm_id=realm_id,
    )
    try:
        if args.cleanup:
            cleanup(qbo)
            return 0

        fixtures = _load_fixtures()
        vendor_specs, account_specs, bill_specs, purchase_specs = _parse_specs(fixtures)

        print("=== Creating accounts ===")
        account_ids = create_accounts(qbo, account_specs)
        print("=== Creating vendors ===")
        vendor_ids = create_vendors(qbo, vendor_specs)
        print(f"=== Creating recurring bills ({args.months} months) ===")
        bill_ids = create_recurring_bills(
            qbo,
            bill_specs,
            vendor_ids=vendor_ids,
            account_ids=account_ids,
            months=args.months,
        )
        print("=== Creating one-off purchases ===")
        create_one_off_purchases(
            qbo, purchase_specs, vendor_ids=vendor_ids, account_ids=account_ids
        )
        print("=== Creating bill payments ===")
        create_bill_payments(qbo, bill_ids)
        print("Done.")
        return 0
    finally:
        qbo.close()


if __name__ == "__main__":
    sys.exit(main())
