#!/usr/bin/env python3
"""Seed Chargebee Test Site with realistic subscription data via Time Machine.

Mirrors deploy/seed/stripe_seed.py: creates a deterministic cohort of
~19 customers across three tiers, advances Chargebee's site-wide
``delorean`` Time Machine month-by-month for ~18 months, and simulates
churn, reactivation, upgrades, downgrades, and trial conversions —
producing the full webhook stream the Chargebee connector translates
into canonical events.

Unlike Stripe (where each test clock is per-customer and capped at 3),
Chargebee's Time Machine is site-wide: one ``travel_forward`` call
advances every subscription on the test site. The script is therefore
~30 % shorter than stripe_seed.py.

Plan structure (mirrors the Stripe seed for cross-provider comparability):

    Starter      — $20/mo flat (metered usage isn't seeded here; add later)
    Professional — $79/mo or $790/yr
    Enterprise   — $249/mo or $2,490/yr

Prerequisites:
    1. A Chargebee Test Site (sign up at chargebee.com — pick "Test Site").
    2. The site's API key (Settings → API Keys → "Full Access Test Key").
    3. ``pip install chargebee`` (already in pyproject deps).
    4. Webhook receiver (smee.io or ngrok) forwarding the site's webhooks
       to ``localhost:8000/api/webhooks/chargebee``. Webhook URL is
       registered in Chargebee under Settings → Webhooks.

Environment:
    CHARGEBEE_SITE          — site name without ``.chargebee.com``
                              suffix (e.g. ``acme-test``)
    CHARGEBEE_API_KEY       — full-access test API key
                              (starts with ``test_``)

Usage:
    python chargebee_seed.py                 # full seed
    python chargebee_seed.py --customers 5
    python chargebee_seed.py --months 3
    python chargebee_seed.py --cleanup       # delete seeded entities
"""

from __future__ import annotations

import argparse
import contextlib
import os
import random
import sys
import time
from datetime import UTC, datetime, timedelta

import chargebee

METADATA_SEED_TAG = {"seed": "tidemill"}

# Currency-tier blends for visible segmentation in default dashboards.
COUNTRIES = ["US", "GB", "DE", "FR", "CA", "AU"]
CURRENCIES = ["USD", "EUR", "GBP"]
CANCEL_REASONS = [
    "not_paid",
    "no_card",
    "fraud_review_failed",
    "non_compliant_eu_customer",
    "tax_calculation_failed",
    "currency_incompatible_with_gateway",
    "non_compliant_customer",
]

# (name_prefix, plan, billing, action, change_month, reactivate_month)
ARCHETYPES = [
    ("Active Starter", "Starter", "monthly", "active", None, None),
    ("Active Starter", "Starter", "monthly", "active", None, None),
    ("Active Monthly Pro", "Professional", "monthly", "active", None, None),
    ("Active Monthly Pro", "Professional", "monthly", "active", None, None),
    ("Active Annual Pro", "Professional", "yearly", "active", None, None),
    ("Active Annual Enterprise", "Enterprise", "yearly", "active", None, None),
    ("Churned Starter", "Starter", "monthly", "churn", 1, None),
    ("Upgraded Starter→Pro", "Starter", "monthly", "upgrade", 1, None),
    ("Downgraded Pro→Starter", "Professional", "monthly", "downgrade", 2, None),
    ("Churned Pro", "Professional", "monthly", "churn", 3, None),
    ("Upgraded Starter→Pro late", "Starter", "monthly", "upgrade", 4, None),
    ("Late Churned Starter", "Starter", "monthly", "churn", 5, None),
    ("Late Downgraded Pro→Starter", "Professional", "monthly", "downgrade", 4, None),
    ("Churn→Reactivate Starter", "Starter", "monthly", "churn_reactivate", 1, 3),
    ("Churn→Reactivate Pro", "Professional", "monthly", "churn_reactivate", 2, 4),
    ("Trial→Active Starter", "trial", "monthly", "trial_convert", 1, None),
    ("Trial→Expired", "trial", "monthly", "trial_expire", None, None),
    ("Active Starter EUR", "Starter", "monthly", "active", None, None),
    ("Active Pro GBP", "Professional", "monthly", "active", None, None),
]

# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

ITEM_FAMILY_ID = "tidemill"

# Item + ItemPrice IDs are deterministic so re-runs/cleanups are predictable.
ITEM_IDS = {
    "Starter": "tidemill-starter",
    "Professional": "tidemill-professional",
    "Enterprise": "tidemill-enterprise",
}

# Map (plan, billing, currency) → item_price ID.
ITEM_PRICE_IDS: dict[tuple[str, str, str], str] = {}

# Set by ``_configure_chargebee``. Each operation runs against this client.
cb: chargebee.Chargebee


def _ip_id(plan: str, billing: str, currency: str) -> str:
    return f"{ITEM_IDS[plan]}-{currency}-{billing}"


# Plans listed here are the canonical (plan, currency, billing) triples we
# create item_prices for. Used both to populate ``ITEM_PRICE_IDS`` and to
# guide currency selection per archetype.
_PLAN_VARIANTS: list[tuple[str, int, list[tuple[str, str]]]] = [
    ("Starter", 2000, [("USD", "monthly")]),  # $20/mo
    (
        "Professional",
        7900,
        [("USD", "monthly"), ("USD", "yearly"), ("GBP", "monthly")],
    ),
    (
        "Enterprise",
        24900,
        [
            ("USD", "monthly"),
            ("USD", "yearly"),
            ("EUR", "monthly"),
        ],
    ),
]


def _ensure_family() -> None:
    """Item families nest items in Chargebee. Idempotent."""
    try:
        cb.ItemFamily.create(
            {
                "id": ITEM_FAMILY_ID,
                "name": "Tidemill (seed)",
            }
        )
    except chargebee.APIError as exc:  # pragma: no cover
        if exc.api_error_code != "duplicate_entry":
            raise


def create_catalog() -> None:
    """Create the three items + their currency/billing-period item prices.

    Each create call is idempotent on `id` — Chargebee returns an
    ``api_error_code='duplicate_entry'`` on re-create, which we swallow
    so reruns of the seed don't fail.
    """
    for name, monthly_cents, currency_billings in _PLAN_VARIANTS:
        item_id = ITEM_IDS[name]
        _create_item(item_id, name)
        for currency, billing in currency_billings:
            ip_id = _ip_id(name, billing, currency)
            ITEM_PRICE_IDS[(name, billing, currency)] = ip_id
            # Yearly price is 10× monthly (mirrors the Stripe seed's
            # discount-for-annual convention; tweak if you want a
            # different multiplier).
            cents = monthly_cents * (10 if billing == "yearly" else 1)
            _create_item_price(
                ip_id=ip_id,
                item_id=item_id,
                price_cents=cents,
                currency=currency,
                period_unit="year" if billing == "yearly" else "month",
            )


def _create_item(item_id: str, name: str) -> None:
    try:
        cb.Item.create(
            {
                "id": item_id,
                "name": name,
                "type": "plan",
                "item_family_id": ITEM_FAMILY_ID,
                "metadata": METADATA_SEED_TAG,
            }
        )
        print(f"  Item:        {item_id}")
    except chargebee.APIError as exc:  # pragma: no cover — depends on live API
        if exc.api_error_code != "duplicate_entry":
            raise


def _create_item_price(
    *,
    ip_id: str,
    item_id: str,
    price_cents: int,
    currency: str,
    period_unit: str,
) -> None:
    try:
        cb.ItemPrice.create(
            {
                "id": ip_id,
                "item_id": item_id,
                "name": ip_id,
                "pricing_model": "flat_fee",
                "price": price_cents,
                "currency_code": currency,
                "period": 1,
                "period_unit": period_unit,
                "metadata": METADATA_SEED_TAG,
            }
        )
        print(f"  ItemPrice:   {ip_id}  ({price_cents / 100:.0f} {currency}/{period_unit})")
    except chargebee.APIError as exc:  # pragma: no cover
        if exc.api_error_code != "duplicate_entry":
            raise


# ---------------------------------------------------------------------------
# Customers and subscriptions
# ---------------------------------------------------------------------------


def _customer_id(index: int) -> str:
    return f"seed-cb-{index}"


def create_customer(index: int, name: str, country: str) -> None:
    try:
        cb.Customer.create(
            {
                "id": _customer_id(index),
                "first_name": name,
                "email": f"seed-cb-{index}@test.example.com",
                "billing_address": {"first_name": name, "country": country},
                "meta_data": {**METADATA_SEED_TAG, "archetype": name, "country": country},
            }
        )
    except chargebee.APIError as exc:  # pragma: no cover
        if exc.api_error_code != "duplicate_entry":
            raise


def create_subscription(
    *,
    index: int,
    plan: str,
    billing: str,
    currency: str,
    trial_end: int | None = None,
) -> str:
    """Create a subscription on the named plan; return the subscription ID.

    For ``trial`` plans we use the Starter item_price + a ``trial_end``
    timestamp so Chargebee fires the trial-conversion webhook when the
    Time Machine crosses the boundary.
    """
    if plan == "trial":
        plan = "Starter"
        billing = "monthly"
    ip_id = ITEM_PRICE_IDS[(plan, billing, currency)]
    sub_id = f"sub-{index}-{plan.lower()}"
    payload: dict[str, object] = {
        "id": sub_id,
        "subscription_items": [{"item_price_id": ip_id, "quantity": 1}],
        "meta_data": METADATA_SEED_TAG,
    }
    if trial_end is not None:
        payload["trial_end"] = trial_end
    try:
        cb.Subscription.create_with_items(_customer_id(index), payload)
    except chargebee.APIError as exc:  # pragma: no cover
        if exc.api_error_code != "duplicate_entry":
            raise
    return sub_id


# ---------------------------------------------------------------------------
# Time Machine
# ---------------------------------------------------------------------------

TIME_MACHINE_NAME = "delorean"


def time_machine_status() -> str:
    """Return the current ``time_travel_status`` of the site's clock."""
    result = cb.TimeMachine.retrieve(TIME_MACHINE_NAME)
    return str(result.time_machine.time_travel_status)


def travel_forward(target_ts: int) -> None:
    """Advance the site clock to *target_ts* and block until it lands.

    Time travel is async on Chargebee's side — we poll
    ``time_travel_status`` until it leaves ``in_progress``. A
    ``failed`` outcome raises so the seed surfaces the bad state
    instead of writing data against a wedged clock.
    """
    cb.TimeMachine.travel_forward(
        TIME_MACHINE_NAME,
        {"destination_time": target_ts},
    )
    deadline = time.time() + 300
    while time.time() < deadline:
        status = time_machine_status()
        if status == "succeeded":
            return
        if status == "failed":
            raise RuntimeError("Time travel failed — check Chargebee dashboard")
        time.sleep(2)
    raise TimeoutError(f"Time travel to {target_ts} didn't finish within 5 min")


# ---------------------------------------------------------------------------
# Lifecycle helpers
# ---------------------------------------------------------------------------


def cancel_sub(sub_id: str, *, immediate: bool, reason: str | None = None) -> None:
    """Cancel a subscription. *immediate* True means now; False means end-of-term."""
    payload: dict[str, object] = {
        "cancel_option": "immediately" if immediate else "end_of_term",
    }
    if reason is not None:
        payload["cancel_reason_code"] = reason
    try:
        cb.Subscription.cancel_for_items(sub_id, payload)
    except chargebee.APIError as exc:  # pragma: no cover
        if exc.api_error_code in ("subscription_not_cancellable", "operation_not_supported"):
            return
        raise


def reactivate_sub(sub_id: str) -> None:
    """Re-activate a cancelled subscription.

    SDK 3.x has no ``reactivate_with_items`` — the live items from the
    last active period are restored automatically by ``reactivate``.
    """
    try:
        cb.Subscription.reactivate(sub_id)
    except chargebee.APIError as exc:  # pragma: no cover
        if exc.api_error_code == "subscription_not_in_required_state":
            return
        raise


def change_sub_plan(sub_id: str, *, plan: str, billing: str, currency: str) -> None:
    ip_id = ITEM_PRICE_IDS[(plan, billing, currency)]
    cb.Subscription.update_for_items(
        sub_id,
        {
            "subscription_items": [{"item_price_id": ip_id, "quantity": 1}],
            "replace_items_list": True,
        },
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup() -> None:
    """Delete every entity tagged ``seed=tidemill``.

    Chargebee deletes cascade: dropping subscriptions auto-removes their
    invoices; deleting items removes their item_prices. Best-effort —
    Chargebee occasionally rejects deletes for in-flight test data and
    we continue.
    """
    print("=== Cleanup ===")
    # Subscriptions first (FKs from invoices).
    for entry in cb.Subscription.list({"limit": 100}).list:
        sub = entry.subscription
        if (sub.meta_data or {}).get("seed") != "tidemill":
            continue
        with contextlib.suppress(chargebee.APIError):
            cb.Subscription.delete(sub.id)
    for entry in cb.Customer.list({"limit": 100}).list:
        cust = entry.customer
        if (cust.meta_data or {}).get("seed") != "tidemill":
            continue
        with contextlib.suppress(chargebee.APIError):
            cb.Customer.delete(cust.id)
    # Catalog last so price refs from canceled subs don't dangle.
    for entry in cb.ItemPrice.list({"limit": 100}).list:
        ip = entry.item_price
        if (ip.metadata or {}).get("seed") != "tidemill":
            continue
        with contextlib.suppress(chargebee.APIError):
            cb.ItemPrice.delete(ip.id)
    for entry in cb.Item.list({"limit": 100}).list:
        item = entry.item
        if (item.metadata or {}).get("seed") != "tidemill":
            continue
        with contextlib.suppress(chargebee.APIError):
            cb.Item.delete(item.id)
    with contextlib.suppress(chargebee.APIError):
        cb.ItemFamily.delete(ITEM_FAMILY_ID)
    print("Cleanup done.")


# ---------------------------------------------------------------------------
# Main seed flow
# ---------------------------------------------------------------------------


def seed(num_customers: int, num_months: int) -> None:
    start = datetime.now(UTC).replace(day=1) - timedelta(days=num_months * 31)
    start = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    bar = "=" * 60
    print(f"\n{bar}")
    print("Chargebee Test Seed")
    print(f"  Customers:  {num_customers}")
    print(f"  Months:     {num_months}")
    print(f"  Start date: {start.date()}")
    print(f"{bar}\n")

    print("=== Catalog ===")
    _ensure_family()
    create_catalog()

    archetypes = (ARCHETYPES * ((num_customers // len(ARCHETYPES)) + 1))[:num_customers]
    entries: list[dict[str, object]] = []

    print(f"\n=== Creating {num_customers} customers + subs (clock at {start.date()}) ===")
    # Time Machine only travels forward; the seed assumes a fresh test
    # site (clock at "now"). Travel to the start of the seed window so
    # subscription created_at fall inside it.
    travel_forward(int(start.timestamp()))

    for i, (name, plan, billing, action, change_month, reactivate_month) in enumerate(archetypes):
        country = COUNTRIES[i % len(COUNTRIES)]
        # Currency rotation only on plans with non-USD variants; everything
        # else stays USD so the upgrade/downgrade transitions don't have to
        # juggle cross-currency switches.
        eligible_currency = (
            (plan == "Professional" and billing == "monthly")
            or (plan == "Enterprise" and billing == "monthly")
        ) and action == "active"
        currency = CURRENCIES[i % len(CURRENCIES)] if eligible_currency else "USD"
        # Fall back to USD when the plan has no item_price in the
        # rotated currency (e.g. Starter is USD-only).
        available_currencies = {c for (p, b, c) in ITEM_PRICE_IDS if p == plan and b == billing}
        if currency not in available_currencies:
            currency = "USD"

        create_customer(i, name, country)

        trial_end: int | None = None
        if plan == "trial":
            trial_end = int((start + timedelta(days=30)).timestamp())

        sub_id = create_subscription(
            index=i,
            plan=plan,
            billing=billing,
            currency=currency,
            trial_end=trial_end,
        )
        entries.append(
            {
                "index": i,
                "sub_id": sub_id,
                "plan": plan,
                "billing": billing,
                "currency": currency,
                "action": action,
                "change_month": change_month,
                "reactivate_month": reactivate_month,
                "active": True,
            }
        )
        print(f"  [{action:18s}] {name} #{i} → {plan}/{billing}/{currency}")

    # Advance month by month.
    print(f"\n=== Advancing {num_months} months ===")
    current = start
    for month in range(num_months):
        # ── trial-expire cancellation runs before the first advance ──
        if month == 0:
            for entry in entries:
                if entry["action"] == "trial_expire":
                    cancel_sub(
                        str(entry["sub_id"]),
                        immediate=True,
                        reason="customer_cancellation",
                    )
                    entry["active"] = False

        # ── scheduled lifecycle changes ──
        for entry in entries:
            if entry.get("change_month") != month:
                continue
            action = str(entry["action"])
            sub_id = str(entry["sub_id"])
            reason = CANCEL_REASONS[int(str(entry["index"])) % len(CANCEL_REASONS)]
            if action == "churn":
                cancel_sub(sub_id, immediate=False, reason=reason)
            elif action == "upgrade":
                change_sub_plan(sub_id, plan="Professional", billing="monthly", currency="USD")
                entry["plan"] = "Professional"
            elif action == "downgrade":
                change_sub_plan(sub_id, plan="Starter", billing="monthly", currency="USD")
                entry["plan"] = "Starter"
            elif action == "trial_convert":
                # Conversion fires automatically when the clock crosses
                # trial_end; nothing to do here. Marker for clarity.
                pass
            elif action == "churn_reactivate":
                cancel_sub(sub_id, immediate=True, reason=reason)
                entry["active"] = False

        # ── reactivations ──
        for entry in entries:
            if entry.get("reactivate_month") != month or entry["active"]:
                continue
            reactivate_sub(str(entry["sub_id"]))
            entry["active"] = True

        # ── advance the clock ──
        current = (current + timedelta(days=32)).replace(day=1)
        target = int(current.timestamp())
        print(f"  → {current.date()}")
        travel_forward(target)
        # Small breather between travels — Chargebee occasionally
        # queues webhook deliveries and pushing through too fast can
        # cause the smee tunnel to fall behind.
        time.sleep(1)

    print(f"\n{bar}\nSeed complete.\nCleanup:  python chargebee_seed.py --cleanup\n{bar}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _configure_chargebee() -> None:
    global cb
    site = os.environ.get("CHARGEBEE_SITE", "").strip()
    api_key = os.environ.get("CHARGEBEE_API_KEY", "").strip()
    if not site or not api_key:
        print(
            "Error: set CHARGEBEE_SITE and CHARGEBEE_API_KEY"
            " (Test Site name + test-mode key starting with 'test_').",
            file=sys.stderr,
        )
        sys.exit(1)
    if not api_key.startswith("test_"):
        print(
            "Error: API key must be a Test Site key (starts with 'test_').",
            file=sys.stderr,
        )
        sys.exit(1)
    cb = chargebee.Chargebee(api_key, site)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Chargebee test data")
    parser.add_argument("--customers", type=int, default=19)
    parser.add_argument("--months", type=int, default=18)
    parser.add_argument("--cleanup", action="store_true", help="Delete seeded entities and exit")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for archetype shuffling")
    args = parser.parse_args()

    _configure_chargebee()
    random.seed(args.seed)

    if args.cleanup:
        cleanup()
        return
    seed(args.customers, args.months)


if __name__ == "__main__":
    main()
