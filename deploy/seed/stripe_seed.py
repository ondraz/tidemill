#!/usr/bin/env python3
"""
Seed Stripe test mode with realistic subscription data using Test Clocks.

Creates customers across usage-based and flat-fee plans, advances time through
6 months of billing cycles, reports metered usage, and simulates churn,
upgrades, and failed payments — generating the full set of webhook events
our connectors need to handle.

Plan structure:
  Starter      — pure PAYG, $0.02 per analytical query
  Professional — $79/mo ($790/yr) base + 10,000 queries included, then $0.01/query
  Enterprise   — $249/mo ($2,490/yr) flat, unlimited queries
  Trial        — 30-day Enterprise-equivalent access, converts to Starter

Prerequisites:
    pip install stripe
    export STRIPE_API_KEY=sk_test_...

Usage:
    python stripe_seed.py                  # full seed (15 customers, 6 months)
    python stripe_seed.py --customers 5    # fewer customers
    python stripe_seed.py --months 3       # shorter history
    python stripe_seed.py --cleanup CLOCK_ID
"""

from __future__ import annotations

import argparse
import os
import random
import sys
import time
from datetime import datetime, timedelta

import stripe

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# (name_prefix, plan, billing, action, monthly_queries)
ARCHETYPES = [
    ("Active Starter", "Starter", "month", "active", 1200),
    ("Active Starter", "Starter", "month", "active", 800),
    ("Active Starter Heavy", "Starter", "month", "active", 5000),
    ("Active Monthly Pro", "Professional", "month", "active", 8000),
    ("Active Monthly Pro", "Professional", "month", "active", 15000),
    ("Active Annual Pro", "Professional", "year", "active", 12000),
    ("Active Annual Enterprise", "Enterprise", "year", "active", 0),
    ("Churned Starter", "Starter", "month", "churn", 600),
    ("Churned Pro", "Professional", "month", "churn", 9000),
    ("Upgraded Starter→Pro", "Starter", "month", "upgrade", 3000),
    ("Upgraded Starter→Pro", "Starter", "month", "upgrade", 4000),
    ("Downgraded Pro→Starter", "Professional", "month", "downgrade", 2000),
    ("Failed Payment Starter", "Starter", "month", "fail_payment", 1000),
    ("Trial→Active Starter", "trial", "month", "trial_convert", 0),
    ("Trial→Expired", "trial", "month", "trial_expire", 0),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def wait_for_clock(clock_id: str) -> None:
    """Poll until the test clock finishes advancing."""
    while True:
        clock = stripe.test_helpers.TestClock.retrieve(clock_id)
        if clock.status == "ready":
            return
        time.sleep(2)


def create_plans() -> dict:
    """Create products and prices, return mapping."""
    result = {}

    # ── Starter: pure PAYG ─────────────────────────────────────────────
    starter_prod = stripe.Product.create(
        name="Starter",
        metadata={"tier": "starter"},
    )
    starter_metered = stripe.Price.create(
        product=starter_prod.id,
        currency="usd",
        unit_amount=2,  # $0.02
        recurring={"interval": "month", "usage_type": "metered"},
        nickname="Starter — $0.02/query",
    )
    result["Starter"] = {
        "product": starter_prod,
        "metered_monthly": starter_metered,
    }
    print(f"  Starter:      PAYG $0.02/query (metered={starter_metered.id})")

    # ── Professional: base fee + metered overage ───────────────────────
    pro_prod = stripe.Product.create(
        name="Professional",
        metadata={"tier": "professional"},
    )
    pro_base_monthly = stripe.Price.create(
        product=pro_prod.id,
        unit_amount=7900,
        currency="usd",
        recurring={"interval": "month"},
        nickname="Professional — $79/mo base",
    )
    pro_base_annual = stripe.Price.create(
        product=pro_prod.id,
        unit_amount=79000,
        currency="usd",
        recurring={"interval": "year"},
        nickname="Professional — $790/yr base",
    )
    pro_metered_monthly = stripe.Price.create(
        product=pro_prod.id,
        currency="usd",
        recurring={"interval": "month", "usage_type": "metered"},
        billing_scheme="tiered",
        tiers_mode="graduated",
        tiers=[
            {"up_to": 10000, "unit_amount": 0},
            {"up_to": "inf", "unit_amount": 1},
        ],
        nickname="Professional — queries (10k free, then $0.01)",
    )
    pro_metered_annual = stripe.Price.create(
        product=pro_prod.id,
        currency="usd",
        recurring={"interval": "year", "usage_type": "metered"},
        billing_scheme="tiered",
        tiers_mode="graduated",
        tiers=[
            {"up_to": 120000, "unit_amount": 0},
            {"up_to": "inf", "unit_amount": 1},
        ],
        nickname="Professional — queries annual (120k free, then $0.01)",
    )
    result["Professional"] = {
        "product": pro_prod,
        "base_monthly": pro_base_monthly,
        "base_annual": pro_base_annual,
        "metered_monthly": pro_metered_monthly,
        "metered_annual": pro_metered_annual,
    }
    print("  Professional: $79/mo | $790/yr + metered overage")

    # ── Enterprise: flat fee ───────────────────────────────────────────
    ent_prod = stripe.Product.create(
        name="Enterprise",
        metadata={"tier": "enterprise"},
    )
    ent_monthly = stripe.Price.create(
        product=ent_prod.id,
        unit_amount=24900,
        currency="usd",
        recurring={"interval": "month"},
        nickname="Enterprise — $249/mo",
    )
    ent_annual = stripe.Price.create(
        product=ent_prod.id,
        unit_amount=249000,
        currency="usd",
        recurring={"interval": "year"},
        nickname="Enterprise — $2,490/yr",
    )
    result["Enterprise"] = {
        "product": ent_prod,
        "monthly": ent_monthly,
        "annual": ent_annual,
    }
    print("  Enterprise:   $249/mo | $2,490/yr (flat)")

    return result


def subscription_items(plans: dict, plan: str, billing: str) -> list[dict]:
    """Return the list of price items for a new subscription."""
    if plan in ("Starter", "trial"):
        return [{"price": plans["Starter"]["metered_monthly"].id}]
    if plan == "Professional":
        suffix = "annual" if billing == "year" else "monthly"
        return [
            {"price": plans["Professional"][f"base_{suffix}"].id},
            {"price": plans["Professional"][f"metered_{suffix}"].id},
        ]
    if plan == "Enterprise":
        key = "annual" if billing == "year" else "monthly"
        return [{"price": plans["Enterprise"][key].id}]
    raise ValueError(f"Unknown plan: {plan}")


def find_metered_item(sub) -> str | None:
    """Find the metered subscription item ID."""
    for item in sub["items"]["data"]:
        if item.price.recurring.usage_type == "metered":
            return item.id
    return None


def report_usage(item_id: str, quantity: int, timestamp: int) -> None:
    """Report usage for a metered subscription item."""
    if quantity > 0:
        stripe.SubscriptionItem.create_usage_record(
            item_id,
            quantity=quantity,
            timestamp=timestamp,
            action="increment",
        )


def random_usage(base: int) -> int:
    """Random usage amount within ±30% of base."""
    if base <= 0:
        return 0
    return random.randint(int(base * 0.7), int(base * 1.3))


def create_customer(
    name: str,
    index: int,
    clock_id: str,
    *,
    failing_card: bool = False,
) -> stripe.Customer:
    """Create a customer attached to the test clock."""
    customer = stripe.Customer.create(
        name=name,
        email=f"seed-{index}@test.example.com",
        test_clock=clock_id,
        metadata={"seed": "true", "archetype": name},
    )

    if failing_card:
        pm = stripe.PaymentMethod.create(
            type="card",
            card={
                "number": "4000000000000002",
                "exp_month": 12,
                "exp_year": 2034,
                "cvc": "123",
            },
        )
        stripe.PaymentMethod.attach(pm.id, customer=customer.id)
        stripe.Customer.modify(
            customer.id,
            invoice_settings={"default_payment_method": pm.id},
        )
    else:
        stripe.Customer.modify(
            customer.id,
            payment_method="pm_card_visa",
            invoice_settings={"default_payment_method": "pm_card_visa"},
        )

    return customer


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def seed(num_customers: int, num_months: int) -> str:
    """Create seed data. Returns the test clock ID for cleanup."""
    start_date = datetime.utcnow().replace(day=1) - timedelta(days=num_months * 31)
    start_date = start_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    start_ts = int(start_date.timestamp())

    print(f"\n{'=' * 60}")
    print("Stripe Test Seed")
    print(f"  Customers:  {num_customers}")
    print(f"  Months:     {num_months}")
    print(f"  Start date: {start_date.date()}")
    print(f"{'=' * 60}\n")

    # 1. Create plans
    print("Creating plans...")
    plans = create_plans()

    # 2. Create test clock
    print("\nCreating test clock...")
    clock = stripe.test_helpers.TestClock.create(
        frozen_time=start_ts,
        name=f"Seed {start_date.date()} → {datetime.utcnow().date()}",
    )
    print(f"  Clock: {clock.id} (frozen at {start_date.date()})")

    # 3. Create customers and subscriptions
    archetypes = (ARCHETYPES * ((num_customers // len(ARCHETYPES)) + 1))[:num_customers]
    entries = []

    print(f"\nCreating {num_customers} customers and subscriptions...")
    for i, (name, plan, billing, action, base_usage) in enumerate(archetypes):
        failing = action == "fail_payment"
        customer = create_customer(f"{name} #{i + 1}", i, clock.id, failing_card=failing)

        items = subscription_items(plans, plan, billing)

        trial_end = None
        if plan == "trial":
            trial_end = start_ts + 30 * 86400  # 30-day trial

        sub = stripe.Subscription.create(
            customer=customer.id,
            items=items,
            trial_end=trial_end if trial_end else "now",
        )

        entries.append(
            {
                "customer": customer,
                "subscription": sub,
                "action": action,
                "plan": plan,
                "billing": billing,
                "base_usage": base_usage,
                "metered_item": find_metered_item(sub),
            }
        )

        plan_label = "Trial (→Starter)" if plan == "trial" else f"{plan} ({billing})"
        print(f"  [{action:14s}] {name} #{i + 1} → {plan_label}")

    # 4. Advance through months
    print(f"\nAdvancing time through {num_months} months...")
    current = start_date

    for month in range(num_months):
        # ── Cancel trial-expire subs before first advance (still in trial) ──
        if month == 0:
            for entry in entries:
                if entry["action"] == "trial_expire":
                    stripe.Subscription.cancel(entry["subscription"].id)
                    entry["metered_item"] = None
                    print(f"  → Cancelled trial for {entry['customer'].name}")

        # ── Month 2 actions: churn, upgrade, downgrade, trial activation ──
        if month == 1:
            for entry in entries:
                action = entry["action"]
                sub = entry["subscription"]
                cust = entry["customer"]

                if action == "churn":
                    stripe.Subscription.modify(sub.id, cancel_at_period_end=True)
                    print(f"  → Marked {cust.name} for cancellation")

                elif action == "upgrade":
                    # Starter → Professional monthly
                    old_items = sub["items"]["data"]
                    sub = stripe.Subscription.modify(
                        sub.id,
                        items=[
                            {"id": old_items[0].id, "deleted": True},
                            {"price": plans["Professional"]["base_monthly"].id},
                            {"price": plans["Professional"]["metered_monthly"].id},
                        ],
                        proration_behavior="create_prorations",
                    )
                    entry["subscription"] = sub
                    entry["metered_item"] = find_metered_item(sub)
                    entry["plan"] = "Professional"
                    entry["base_usage"] = 12000
                    print(f"  → Upgraded {cust.name} to Professional")

                elif action == "downgrade":
                    # Professional → Starter
                    old_items = sub["items"]["data"]
                    modify_items = [{"id": it.id, "deleted": True} for it in old_items]
                    modify_items.append({"price": plans["Starter"]["metered_monthly"].id})
                    sub = stripe.Subscription.modify(
                        sub.id,
                        items=modify_items,
                        proration_behavior="create_prorations",
                    )
                    entry["subscription"] = sub
                    entry["metered_item"] = find_metered_item(sub)
                    entry["plan"] = "Starter"
                    print(f"  → Downgraded {cust.name} to Starter")

                elif action == "trial_convert":
                    # Trial ended, now billing as Starter — start reporting usage
                    entry["base_usage"] = 1500
                    print(f"  → Trial converted for {cust.name}, now active Starter")

        # ── Report usage for metered subscriptions ──
        mid_month_ts = int((current + timedelta(days=15)).timestamp())
        for entry in entries:
            if entry["metered_item"] and entry["base_usage"] > 0:
                usage = random_usage(entry["base_usage"])
                report_usage(entry["metered_item"], usage, mid_month_ts)

        # ── Advance clock ──
        current += timedelta(days=32)
        current = current.replace(day=1)
        now = datetime.utcnow()
        if current > now:
            current = now

        target_ts = int(current.timestamp())
        print(f"  Advancing to {current.date()}...")
        stripe.test_helpers.TestClock.advance(clock.id, frozen_time=target_ts)
        wait_for_clock(clock.id)

    print(f"\n{'=' * 60}")
    print("Seed complete!")
    print(f"  Clock ID: {clock.id}")
    print(f"  Cleanup:  python stripe_seed.py --cleanup {clock.id}")
    print(f"{'=' * 60}\n")

    return clock.id


def cleanup(clock_id: str) -> None:
    """Delete a test clock and all its resources."""
    print(f"Deleting test clock {clock_id} and all associated resources...")
    stripe.test_helpers.TestClock.delete(clock_id)
    print("Done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Stripe test data")
    parser.add_argument(
        "--customers", type=int, default=15, help="Number of customers (default: 15)"
    )
    parser.add_argument("--months", type=int, default=6, help="Months of history (default: 6)")
    parser.add_argument("--cleanup", type=str, metavar="CLOCK_ID", help="Delete a test clock")
    args = parser.parse_args()

    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        print("Error: Set STRIPE_API_KEY environment variable (sk_test_...)", file=sys.stderr)
        sys.exit(1)

    if not api_key.startswith("sk_test_"):
        print("Error: This script only works with test mode keys (sk_test_...)", file=sys.stderr)
        sys.exit(1)

    stripe.api_key = api_key

    if args.cleanup:
        cleanup(args.cleanup)
    else:
        seed(args.customers, args.months)


if __name__ == "__main__":
    main()
