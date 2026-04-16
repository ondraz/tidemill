#!/usr/bin/env python3
"""Seed Stripe test mode with realistic subscription data using Test Clocks.

Creates customers across usage-based and flat-fee plans, advances time through
6 months of billing cycles, reports metered usage, and simulates churn,
reactivation, upgrades, and failed payments — generating the full set of webhook
events our connectors need to handle.

Plan structure:
  Starter      — pure PAYG, $0.02 per analytical query
  Professional — $79/mo ($790/yr) base + 10,000 queries included, then $0.01/query
  Enterprise   — $249/mo ($2,490/yr) flat, unlimited queries
  Trial        — 30-day Enterprise-equivalent access, converts to Starter

Prerequisites:
    pip install stripe
    export STRIPE_API_KEY=sk_test_...

Usage:
    python stripe_seed.py                  # full seed (19 customers, 6 months)
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
from datetime import UTC, datetime, timedelta

import stripe

METER_EVENT_NAME = "analytical_query"

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# (name_prefix, plan, billing, action, monthly_queries, change_month, reactivate_month)
#   change_month: loop iteration when the lifecycle action fires (None = stays active).
#   reactivate_month: for churn_reactivate, the month a new subscription is created
#     on the same plan (must be > change_month + 1 to leave a full offline month).
#   With --months 6, month 0 ≈ start date, month 5 ≈ 5 months later.
ARCHETYPES = [
    ("Active Starter", "Starter", "month", "active", 50, None, None),
    ("Active Starter", "Starter", "month", "active", 30, None, None),
    ("Active Starter Heavy", "Starter", "month", "active", 120, None, None),
    ("Active Monthly Pro", "Professional", "month", "active", 8000, None, None),
    ("Active Monthly Pro", "Professional", "month", "active", 15000, None, None),
    ("Active Annual Pro", "Professional", "year", "active", 12000, None, None),
    ("Active Annual Enterprise", "Enterprise", "year", "active", 0, None, None),
    # Early changes (months 1–2)
    ("Churned Starter", "Starter", "month", "churn", 20, 1, None),
    ("Upgraded Starter→Pro", "Starter", "month", "upgrade", 80, 1, None),
    ("Downgraded Pro→Starter", "Professional", "month", "downgrade", 2000, 2, None),
    # Mid changes (month 3)
    ("Churned Pro", "Professional", "month", "churn", 9000, 3, None),
    # Late changes (months 4–5)
    ("Upgraded Starter→Pro", "Starter", "month", "upgrade", 60, 4, None),
    ("Late Churned Starter", "Starter", "month", "churn", 45, 5, None),
    ("Late Downgraded Pro→Starter", "Professional", "month", "downgrade", 3000, 4, None),
    # Churn then reactivate (win-back)
    ("Churn→Reactivate Starter", "Starter", "month", "churn_reactivate", 40, 1, 3),
    ("Churn→Reactivate Pro", "Professional", "month", "churn_reactivate", 5000, 2, 4),
    # Ongoing / special
    ("Failed Payment Starter", "Starter", "month", "fail_payment", 40, None, None),
    ("Trial→Active Starter", "trial", "month", "trial_convert", 25, 1, None),
    ("Trial→Expired", "trial", "month", "trial_expire", 0, None, None),
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

    # ── Billing Meter (shared across all metered prices) ───────────────
    # Reuse existing active meter if one exists for our event name
    meter = None
    for m in stripe.billing.Meter.list(limit=100).data:
        if m.event_name == METER_EVENT_NAME and m.status == "active":
            meter = m
            break
    if meter is None:
        meter = stripe.billing.Meter.create(
            display_name="Analytical Queries",
            event_name=METER_EVENT_NAME,
            default_aggregation={"formula": "sum"},
        )
    result["_meter"] = meter
    print(f"  Meter:        {meter.id} (event={METER_EVENT_NAME})")

    # ── Starter: $20/mo base + $1/query metered ─────────────────────────
    starter_prod = stripe.Product.create(
        name="Starter",
        metadata={"tier": "starter"},
    )
    starter_base = stripe.Price.create(
        product=starter_prod.id,
        unit_amount=2000,  # $20/mo
        currency="usd",
        recurring={"interval": "month"},
        nickname="Starter — $20/mo base",
    )
    starter_metered = stripe.Price.create(
        product=starter_prod.id,
        currency="usd",
        unit_amount=100,  # $1/query
        recurring={"interval": "month", "meter": meter.id, "usage_type": "metered"},
        nickname="Starter — $1/query",
    )
    result["Starter"] = {
        "product": starter_prod,
        "base_monthly": starter_base,
        "metered_monthly": starter_metered,
    }
    print(
        f"  Starter:      $20/mo + $1/query (base={starter_base.id}, metered={starter_metered.id})"
    )

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
        recurring={"interval": "month", "meter": meter.id, "usage_type": "metered"},
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
        recurring={"interval": "year", "meter": meter.id, "usage_type": "metered"},
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
        return [
            {"price": plans["Starter"]["base_monthly"].id},
            {"price": plans["Starter"]["metered_monthly"].id},
        ]
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


def report_usage(customer_id: str, quantity: int, timestamp: int) -> None:
    """Report usage via billing meter event."""
    if quantity > 0:
        stripe.billing.MeterEvent.create(
            event_name=METER_EVENT_NAME,
            payload={
                "value": str(quantity),
                "stripe_customer_id": customer_id,
            },
            timestamp=timestamp,
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

    # Attach a card that declines on charge (4000000000000341) for fail_payment,
    # or a normal Visa for everyone else.
    # tok_chargeCustomerFail attaches OK but fails on charge
    token = "tok_chargeCustomerFail" if failing_card else "tok_visa"
    pm = stripe.PaymentMethod.create(type="card", card={"token": token})
    stripe.PaymentMethod.attach(pm.id, customer=customer.id)
    stripe.Customer.modify(
        customer.id,
        invoice_settings={"default_payment_method": pm.id},
    )

    return customer


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


MAX_CUSTOMERS_PER_CLOCK = 3


def seed(num_customers: int, num_months: int) -> str:
    """Create seed data. Returns comma-separated test clock IDs for cleanup."""
    start_date = datetime.now(UTC).replace(day=1) - timedelta(days=num_months * 31)
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

    # 2. Create customers grouped into test clocks (max 3 per clock)
    archetypes = (ARCHETYPES * ((num_customers // len(ARCHETYPES)) + 1))[:num_customers]
    clocks = []
    entries = []

    print(f"\nCreating {num_customers} customers and subscriptions...")
    for i, (
        name,
        plan,
        billing,
        action,
        base_usage,
        change_month,
        reactivate_month,
    ) in enumerate(archetypes):
        # Create a new clock when needed
        if i % MAX_CUSTOMERS_PER_CLOCK == 0:
            batch = i // MAX_CUSTOMERS_PER_CLOCK + 1
            clock = stripe.test_helpers.TestClock.create(
                frozen_time=start_ts,
                name=f"Seed batch {batch} — {start_date.date()}",
            )
            clocks.append(clock)
            print(f"  Clock {batch}: {clock.id}")

        failing = action == "fail_payment"
        customer = create_customer(f"{name} #{i + 1}", i, clocks[-1].id, failing_card=failing)

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
                "active": True,
                "change_month": change_month,
                "reactivate_month": reactivate_month,
            }
        )

        plan_label = "Trial (→Starter)" if plan == "trial" else f"{plan} ({billing})"
        print(f"  [{action:14s}] {name} #{i + 1} → {plan_label}")

    # 3. Advance through months
    #
    # Each month we also add new trial subscriptions.  Some convert to Starter
    # after 30 days and some churn, producing realistic MoM growth.
    customer_counter = len(entries)

    print(f"\nAdvancing time through {num_months} months ({len(clocks)} clocks)...")
    current = start_date

    for month in range(num_months):
        # ── Cancel trial-expire subs before first advance (still in trial) ──
        if month == 0:
            for entry in entries:
                if entry["action"] == "trial_expire":
                    stripe.Subscription.cancel(entry["subscription"].id)
                    entry["active"] = False
                    print(f"  → Cancelled trial for {entry['customer'].name}")

        # ── Scheduled lifecycle changes (churn, upgrade, downgrade, trial) ──
        for entry in entries:
            if entry.get("change_month") != month:
                continue
            action = entry["action"]
            sub = entry["subscription"]
            cust = entry["customer"]

            if action == "churn":
                stripe.Subscription.modify(sub.id, cancel_at_period_end=True)
                print(f"  → Marked {cust.name} for cancellation")

            elif action == "upgrade":
                # Starter → Professional monthly
                old_items = sub["items"]["data"]
                modify_items = [{"id": it.id, "deleted": True} for it in old_items]
                modify_items.append({"price": plans["Professional"]["base_monthly"].id})
                modify_items.append({"price": plans["Professional"]["metered_monthly"].id})
                sub = stripe.Subscription.modify(
                    sub.id,
                    items=modify_items,
                    proration_behavior="create_prorations",
                )
                entry["subscription"] = sub
                entry["plan"] = "Professional"
                entry["base_usage"] = 12000
                print(f"  → Upgraded {cust.name} to Professional")

            elif action == "downgrade":
                # Professional → Starter
                old_items = sub["items"]["data"]
                modify_items = [{"id": it.id, "deleted": True} for it in old_items]
                modify_items.append({"price": plans["Starter"]["base_monthly"].id})
                modify_items.append({"price": plans["Starter"]["metered_monthly"].id})
                sub = stripe.Subscription.modify(
                    sub.id,
                    items=modify_items,
                    proration_behavior="create_prorations",
                )
                entry["subscription"] = sub
                entry["plan"] = "Starter"
                entry["base_usage"] = 40
                print(f"  → Downgraded {cust.name} to Starter")

            elif action == "trial_convert":
                # Trial ended, now billing as Starter — start reporting usage
                entry["base_usage"] = 25
                print(f"  → Trial converted for {cust.name}, now active Starter")

            elif action == "churn_reactivate":
                # Immediate cancel so the customer is clearly gone until reactivation
                stripe.Subscription.cancel(sub.id)
                entry["active"] = False
                print(f"  → Cancelled {cust.name} (reactivates month {entry['reactivate_month']})")

        # ── Reactivate previously-churned customers on the same plan ──
        for entry in entries:
            if entry.get("reactivate_month") != month or entry["active"]:
                continue
            cust = entry["customer"]
            items = subscription_items(plans, entry["plan"], entry["billing"])
            new_sub = stripe.Subscription.create(
                customer=cust.id,
                items=items,
                trial_end="now",
            )
            entry["subscription"] = new_sub
            entry["active"] = True
            print(f"  → Reactivated {cust.name} on {entry['plan']}")

        # ── Handle previous month's trial outcomes (convert or churn) ──
        for entry in entries:
            if entry.get("_trial_outcome") == month:
                if entry["action"] == "trial_monthly_convert":
                    entry["base_usage"] = random.randint(15, 60)
                    print(f"  → Trial converted: {entry['customer'].name}")
                elif entry["action"] == "trial_monthly_churn":
                    stripe.Subscription.cancel(entry["subscription"].id)
                    entry["active"] = False
                    print(f"  → Trial churned: {entry['customer'].name}")

        # ── Add new trial customers for this month ──
        if month < num_months - 1:  # don't add trials in the last month
            new_trials = random.randint(2, 5)
            convert_count = random.randint(1, new_trials - 1) if new_trials > 1 else 1
            current_ts = int(current.timestamp())

            print(
                f"  + Adding {new_trials} new trials "
                f"({convert_count} will convert, {new_trials - convert_count} will churn)"
            )
            for t in range(new_trials):
                customer_counter += 1
                # New clock for each batch of 3
                if t % MAX_CUSTOMERS_PER_CLOCK == 0:
                    batch = len(clocks) + 1
                    clock = stripe.test_helpers.TestClock.create(
                        frozen_time=current_ts,
                        name=f"Seed batch {batch} — trials {current.date()}",
                    )
                    clocks.append(clock)

                will_convert = t < convert_count
                action = "trial_monthly_convert" if will_convert else "trial_monthly_churn"
                label = "→convert" if will_convert else "→churn"
                cname = f"Trial {current.strftime('%b')} {label} #{customer_counter}"

                cust = create_customer(cname, customer_counter, clocks[-1].id)
                items = subscription_items(plans, "trial", "month")
                trial_end = current_ts + 30 * 86400

                sub = stripe.Subscription.create(
                    customer=cust.id,
                    items=items,
                    trial_end=trial_end,
                )
                entries.append(
                    {
                        "customer": cust,
                        "subscription": sub,
                        "action": action,
                        "plan": "trial",
                        "billing": "month",
                        "base_usage": 0,
                        "active": True,
                        "_trial_outcome": month + 1,  # process outcome next month
                    }
                )

        # ── Advance all clocks ──
        prev = current
        current += timedelta(days=32)
        current = current.replace(day=1)

        target_ts = int(current.timestamp())
        print(f"  Advancing to {current.date()}...")
        for c in clocks:
            stripe.test_helpers.TestClock.advance(c.id, frozen_time=target_ts)
        for c in clocks:
            wait_for_clock(c.id)

        # ── Report usage via meter events (timestamp in the month just passed) ──
        mid_month_ts = int((prev + timedelta(days=15)).timestamp())
        for entry in entries:
            if entry["active"] and entry["base_usage"] > 0:
                usage = random_usage(entry["base_usage"])
                report_usage(entry["customer"].id, usage, mid_month_ts)

    # ── Final advance to close the last month's billing cycle ──
    current += timedelta(days=32)
    current = current.replace(day=1)
    target_ts = int(current.timestamp())
    print(f"  Final advance to {current.date()} (closing last billing cycle)...")
    for c in clocks:
        stripe.test_helpers.TestClock.advance(c.id, frozen_time=target_ts)
    for c in clocks:
        wait_for_clock(c.id)

    clock_ids = [c.id for c in clocks]
    print(f"\n{'=' * 60}")
    print("Seed complete!")
    print(f"  Clocks: {', '.join(clock_ids)}")
    print("  Cleanup:  python stripe_seed.py --cleanup")
    print(f"{'=' * 60}\n")

    return ",".join(clock_ids)


def cleanup(clock_id: str | None = None) -> None:
    """Delete test clock(s) and all their resources.

    If *clock_id* is given, delete just that clock. Otherwise delete all
    clocks whose name starts with "Seed".
    """
    if clock_id:
        ids = [cid.strip() for cid in clock_id.split(",")]
    else:
        ids = [
            c.id
            for c in stripe.test_helpers.TestClock.list(limit=100).data
            if c.name and c.name.startswith("Seed")
        ]

    if not ids:
        print("No seed clocks found.")
        return

    for cid in ids:
        print(f"Deleting test clock {cid}...")
        stripe.test_helpers.TestClock.delete(cid)
    print(f"Done — deleted {len(ids)} clock(s).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Stripe test data")
    parser.add_argument(
        "--customers", type=int, default=19, help="Number of customers (default: 19)"
    )
    parser.add_argument("--months", type=int, default=6, help="Months of history (default: 6)")
    parser.add_argument(
        "--cleanup",
        nargs="?",
        const="",
        default=None,
        metavar="CLOCK_ID",
        help="Delete seed clocks (specific ID, or all if omitted)",
    )
    args = parser.parse_args()

    api_key = os.environ.get("STRIPE_API_KEY")
    if not api_key:
        print("Error: Set STRIPE_API_KEY environment variable (sk_test_...)", file=sys.stderr)
        sys.exit(1)

    if not api_key.startswith("sk_test_"):
        print("Error: This script only works with test mode keys (sk_test_...)", file=sys.stderr)
        sys.exit(1)

    stripe.api_key = api_key

    if args.cleanup is not None:
        cleanup(args.cleanup or None)
    else:
        seed(args.customers, args.months)


if __name__ == "__main__":
    main()
