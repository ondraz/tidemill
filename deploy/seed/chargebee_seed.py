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
    4. Time Travel enabled on the test site — a one-time dashboard step
       (Settings → Configure Chargebee → Time Machine → enable) that
       can't be done over the API. Enabling wipes the site's
       customers/subscriptions, and a Time Machine handles at most five
       subscriptions/customers, so this seed caps the cohort at five
       regardless of ``--customers``.
    5. Webhook reachable from Chargebee at
       ``/api/webhooks/chargebee``. The default local setup uses
       Tailscale Funnel: ``make chargebee-funnel-up`` exposes
       ``localhost:8000`` on a stable HTTPS URL
       (``https://<host>.<tailnet>.ts.net``). Configure the Chargebee
       webhook to that URL once; see
       ``docs/development/testing.md#chargebee-testing-test-site--time-machine``
       for the full flow.

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
import json
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
#
# A Chargebee Test Site Time Machine handles at most TIME_MACHINE_MAX
# subscriptions/customers (see below), so the seed only instantiates the
# first TIME_MACHINE_MAX entries. They are ordered front-loaded for
# coverage: one steady active account plus one each of churn, upgrade,
# trial conversion, and churn→reactivate, so a 5-customer cohort still
# exercises every lifecycle transition the metrics care about. The
# remaining archetypes are kept for parity with stripe_seed.py and are
# only reached if Chargebee ever lifts the limit.
ARCHETYPES = [
    ("Active Monthly Pro", "Professional", "monthly", "active", None, None),
    ("Churned Pro", "Professional", "monthly", "churn", 3, None),
    ("Upgraded Starter→Pro", "Starter", "monthly", "upgrade", 1, None),
    ("Trial→Active Starter", "trial", "monthly", "trial_convert", 1, None),
    ("Churn→Reactivate Starter", "Starter", "monthly", "churn_reactivate", 1, 3),
    # ── beyond the Time Machine limit; parity with stripe_seed.py ──
    ("Active Starter", "Starter", "monthly", "active", None, None),
    ("Active Starter", "Starter", "monthly", "active", None, None),
    ("Active Monthly Pro", "Professional", "monthly", "active", None, None),
    ("Active Annual Pro", "Professional", "yearly", "active", None, None),
    ("Active Annual Enterprise", "Enterprise", "yearly", "active", None, None),
    ("Churned Starter", "Starter", "monthly", "churn", 1, None),
    ("Downgraded Pro→Starter", "Professional", "monthly", "downgrade", 2, None),
    ("Upgraded Starter→Pro late", "Starter", "monthly", "upgrade", 4, None),
    ("Late Churned Starter", "Starter", "monthly", "churn", 5, None),
    ("Late Downgraded Pro→Starter", "Professional", "monthly", "downgrade", 4, None),
    ("Churn→Reactivate Pro", "Professional", "monthly", "churn_reactivate", 2, 4),
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


def _resolve_variant(
    plan: str, preferred_billing: str, preferred_currency: str
) -> tuple[str, str]:
    """Return the closest available ``(billing, currency)`` for *plan*.

    Falls back to same-billing-different-currency, then to any variant
    for the plan. Raises if no variant exists at all (catalog build
    would have aborted earlier).
    """
    available = {(b, c) for (p, b, c) in ITEM_PRICE_IDS if p == plan}
    if not available:
        raise RuntimeError(f"No item_price configured for plan {plan!r}")
    if (preferred_billing, preferred_currency) in available:
        return preferred_billing, preferred_currency
    same_billing = sorted(c for (b, c) in available if b == preferred_billing)
    if same_billing:
        return preferred_billing, same_billing[0]
    return sorted(available)[0]


# Plans listed here are the canonical (plan, currency, billing) triples we
# attempt to create item_prices for. Chargebee Test Sites pick a single
# base currency at signup; additional currencies must be enabled in
# Settings → Configure Chargebee → Currencies. Variants whose currency
# isn't enabled on the site are skipped silently — see
# ``_create_item_price`` — so the seed adapts to whatever the operator
# has configured.
_PLAN_VARIANTS: list[tuple[str, int, list[tuple[str, str]]]] = [
    (
        "Starter",
        2000,
        [("USD", "monthly"), ("EUR", "monthly"), ("GBP", "monthly")],
    ),
    (
        "Professional",
        7900,
        [
            ("USD", "monthly"),
            ("USD", "yearly"),
            ("EUR", "monthly"),
            ("EUR", "yearly"),
            ("GBP", "monthly"),
        ],
    ),
    (
        "Enterprise",
        24900,
        [
            ("USD", "monthly"),
            ("USD", "yearly"),
            ("EUR", "monthly"),
            ("EUR", "yearly"),
            ("GBP", "monthly"),
        ],
    ),
]


def _already_exists(exc: chargebee.APIError) -> bool:
    """True when a create failed only because the entity already exists.

    Chargebee's duplicate-id signal varies by entity and SDK version:
    some creates return ``api_error_code='duplicate_entry'``, but the
    item catalog (ItemFamily / Item / ItemPrice) in SDK 3.x instead
    returns a generic ``invalid_request`` with a "Code <id> already
    exists" message. ``start_afresh`` clears customers and subscriptions
    but *not* the product catalog, so reruns always re-hit these — match
    either signal so the catalog build stays idempotent.
    """
    if getattr(exc, "api_error_code", None) == "duplicate_entry":
        return True
    return "already exists" in str(exc).lower()


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
        if not _already_exists(exc):
            raise


def create_catalog() -> None:
    """Create the three items + their currency/billing-period item prices.

    Each create call is idempotent on `id` — re-creates are swallowed
    via ``_already_exists`` (start_afresh leaves the catalog intact, so
    reruns always re-hit these). Variants in currencies not enabled on
    the site are skipped (see ``_create_item_price``); if a plan ends up
    with zero variants we abort with a message pointing at the Chargebee
    admin.
    """
    for name, monthly_cents, currency_billings in _PLAN_VARIANTS:
        item_id = ITEM_IDS[name]
        _create_item(item_id, name)
        for currency, billing in currency_billings:
            ip_id = _ip_id(name, billing, currency)
            # Yearly price is 10× monthly (mirrors the Stripe seed's
            # discount-for-annual convention; tweak if you want a
            # different multiplier).
            cents = monthly_cents * (10 if billing == "yearly" else 1)
            if _create_item_price(
                ip_id=ip_id,
                item_id=item_id,
                price_cents=cents,
                currency=currency,
                period_unit="year" if billing == "yearly" else "month",
            ):
                ITEM_PRICE_IDS[(name, billing, currency)] = ip_id

    plans_with_prices = {p for (p, _b, _c) in ITEM_PRICE_IDS}
    missing = sorted(set(ITEM_IDS) - plans_with_prices)
    if missing:
        print(
            "\nError: no currencies enabled on this Chargebee site for plans:"
            f" {', '.join(missing)}.\n"
            "Enable USD/EUR/GBP under\n"
            "  Settings → Configure Chargebee → Currencies\n"
            "in the Chargebee admin, then rerun the seed.",
            file=sys.stderr,
        )
        sys.exit(1)
    enabled = sorted({c for (_p, _b, c) in ITEM_PRICE_IDS})
    print(f"\n  Enabled currencies on this site: {', '.join(enabled)}")


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
        if not _already_exists(exc):
            raise


def _create_item_price(
    *,
    ip_id: str,
    item_id: str,
    price_cents: int,
    currency: str,
    period_unit: str,
) -> bool:
    """Create the item_price; return True on success or duplicate.

    Return False when the currency isn't enabled on this site (the
    Chargebee API rejects with ``param='currency_code'`` /
    ``not in allowed values``). The caller skips this variant.
    """
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
        return True
    except chargebee.APIError as exc:  # pragma: no cover
        if _already_exists(exc):
            return True
        if _is_currency_not_enabled(exc):
            print(f"  ItemPrice:   {ip_id}  (skipped — {currency} not enabled on this site)")
            return False
        raise


def _is_currency_not_enabled(exc: chargebee.APIError) -> bool:
    param = getattr(exc, "param", None) or ""
    if param == "currency_code":
        return True
    return "currency_code" in str(exc).lower() and "not in allowed" in str(exc).lower()


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
                # Offline collection — seed customers have no card on
                # file. Subscriptions still go active and invoices are
                # raised (as payment_due), which is all the subscription
                # analytics need; it just skips the card-charge step that
                # otherwise fails with "no valid card on file".
                "auto_collection": "off",
                "meta_data": {**METADATA_SEED_TAG, "archetype": name, "country": country},
            }
        )
    except chargebee.APIError as exc:  # pragma: no cover
        if not _already_exists(exc):
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
        # Offline collection (see create_customer) — no card required.
        "auto_collection": "off",
        "meta_data": METADATA_SEED_TAG,
    }
    if trial_end is not None:
        payload["trial_end"] = trial_end
    try:
        cb.Subscription.create_with_items(_customer_id(index), payload)
    except chargebee.APIError as exc:  # pragma: no cover
        if not _already_exists(exc):
            raise
    return sub_id


# ---------------------------------------------------------------------------
# Time Machine
# ---------------------------------------------------------------------------

TIME_MACHINE_NAME = "delorean"

# A Chargebee Test Site Time Machine handles at most five subscriptions
# and customers at a time; exceeding it makes every travel return
# ``time_travel_status='failed'``. See
# docs/development/testing.md#chargebee-testing-test-site--time-machine
# and https://www.chargebee.com/docs/2.0/site-configuration/articles-and-faq/limitations-of-time-machine.html
TIME_MACHINE_MAX = 5


def _require_time_travel_enabled(exc: chargebee.APIError) -> None:
    """Convert the opaque 'not enabled' API error into an actionable one.

    Time Travel is a site-level feature that must be switched on once in
    the Chargebee dashboard — it cannot be enabled over the API. Until
    then both ``start_afresh`` and ``travel_forward`` reject with
    ``configuration_incompatible`` / "Time travel is not enabled for this
    site." Re-raise everything else unchanged.
    """
    if getattr(exc, "api_error_code", None) == "configuration_incompatible":
        print(
            "\nError: Time Travel is not enabled on this Chargebee site.\n"
            "Enable it once in the dashboard (test sites only):\n"
            "  Settings → Configure Chargebee → Time Machine → enable\n"
            "Note: enabling wipes the site's customers/subscriptions, and a\n"
            "Time Machine handles at most "
            f"{TIME_MACHINE_MAX} subscriptions/customers.\n"
            "Then rerun the seed. Full setup:\n"
            "  docs/development/testing.md"
            "#chargebee-testing-test-site--time-machine",
            file=sys.stderr,
        )
        sys.exit(1)
    raise exc


# Chargebee runs each hop's billing jobs asynchronously and aborts the
# hop if that batch runs long — error_code ``time_travel_execution_too_long``
# under ``resource_limit_exhausted``. It's intermittent (a full 18-hop run
# often succeeds), but once it fires the session is poisoned: re-issuing
# the hop fails with "a previous time travel failed … start afresh", so it
# can't be resumed in place. We surface it as ``TimeTravelBacklog`` and let
# the caller decide based on how far the window has already been replayed.
_BACKLOG_TRAVEL_ERROR = "time_travel_execution_too_long"


class TimeTravelBacklog(RuntimeError):
    """Chargebee aborted a hop because its job batch ran too long.

    Terminal for the run (the Time Machine session is poisoned
    afterward); the caller decides whether enough of the window has been
    replayed to keep the seeded data.
    """


def _poll_time_travel() -> tuple[str, dict]:
    """Poll until the clock settles; return ``(status, error)``.

    Time travel is async on Chargebee's side. On ``failed`` the parsed
    ``error_json`` is returned (empty dict otherwise) so the caller can
    decide whether the failure is retryable.
    """
    deadline = time.time() + 300
    while time.time() < deadline:
        tm = cb.TimeMachine.retrieve(TIME_MACHINE_NAME).time_machine
        status = str(tm.time_travel_status)
        if status == "succeeded":
            return status, {}
        if status == "failed":
            try:
                return status, json.loads(getattr(tm, "error_json", None) or "{}")
            except (TypeError, ValueError):
                return status, {}
        time.sleep(2)
    raise TimeoutError("Time travel didn't finish within 5 min")


def start_afresh(genesis_ts: int) -> None:
    """Reset the site clock to *genesis_ts* and block until it lands.

    Time Machines only travel forward, so each seed run must rewind to
    the window start before replaying the months. ``start_afresh`` also
    wipes all transactional data (customers, subscriptions, invoices) —
    which is what makes the seed safely re-runnable — so it must run
    before the catalog is (re)created.
    """
    try:
        cb.TimeMachine.start_afresh(TIME_MACHINE_NAME, {"genesis_time": genesis_ts})
    except chargebee.APIError as exc:  # pragma: no cover — depends on live API
        _require_time_travel_enabled(exc)
    status, err = _poll_time_travel()
    if status != "succeeded":
        raise RuntimeError(f"start_afresh failed: {err.get('message') or err or 'unknown'}")


def travel_forward(target_ts: int) -> None:
    """Advance the site clock to *target_ts* and block until it lands.

    Raises ``TimeTravelBacklog`` on Chargebee's job-execution timeout
    (recoverable only by the caller, since the session is poisoned), and
    a plain ``RuntimeError`` on any other failure — most commonly because
    a Time Machine handles at most ``TIME_MACHINE_MAX``
    subscriptions/customers.
    """
    try:
        cb.TimeMachine.travel_forward(
            TIME_MACHINE_NAME,
            {"destination_time": target_ts},
        )
    except chargebee.APIError as exc:  # pragma: no cover — depends on live API
        _require_time_travel_enabled(exc)
    status, err = _poll_time_travel()
    if status == "succeeded":
        return
    if err.get("error_code") == _BACKLOG_TRAVEL_ERROR:
        raise TimeTravelBacklog(err.get("message") or "time-travel job execution too long")
    raise RuntimeError(
        f"Time travel failed: {err.get('message') or err or 'unknown'}. "
        f"A Time Machine handles at most {TIME_MACHINE_MAX} "
        "subscriptions/customers — check the Chargebee dashboard."
    )


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
    if num_customers > TIME_MACHINE_MAX:
        print(
            f"NOTE: a Chargebee Time Machine handles at most {TIME_MACHINE_MAX} "
            f"subscriptions/customers — capping {num_customers} → "
            f"{TIME_MACHINE_MAX}. (Stripe still seeds its full cohort.)"
        )
        num_customers = TIME_MACHINE_MAX

    start = datetime.now(UTC).replace(day=1) - timedelta(days=num_months * 31)
    start = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    bar = "=" * 60
    print(f"\n{bar}")
    print("Chargebee Test Seed")
    print(f"  Customers:  {num_customers}")
    print(f"  Months:     {num_months}")
    print(f"  Start date: {start.date()}")
    print(f"{bar}\n")

    # Rewind the site clock to the window start. Time Machines only move
    # forward, so this is also what makes re-runs work — start_afresh
    # wipes prior data and resets the clock. Must precede the catalog
    # build since start_afresh empties the site.
    print(f"=== Resetting Time Machine to {start.date()} (start afresh) ===")
    start_afresh(int(start.timestamp()))

    print("=== Catalog ===")
    _ensure_family()
    create_catalog()

    archetypes = ARCHETYPES[:num_customers]
    entries: list[dict[str, object]] = []

    print(f"\n=== Creating {num_customers} customers + subs (clock at {start.date()}) ===")

    for i, (name, plan, billing, action, change_month, reactivate_month) in enumerate(archetypes):
        country = COUNTRIES[i % len(COUNTRIES)]
        # Currency rotation only on plans with multiple enabled
        # currency variants; everything else stays on the plan's
        # default so upgrade/downgrade transitions don't juggle
        # cross-currency switches.
        eligible_currency = (
            (plan == "Professional" and billing == "monthly")
            or (plan == "Enterprise" and billing == "monthly")
        ) and action == "active"
        preferred = CURRENCIES[i % len(CURRENCIES)] if eligible_currency else "USD"
        # Resolve to whatever variants the site actually has enabled.
        # For ``trial`` archetype we'll re-resolve against the Starter
        # plan inside ``create_subscription``.
        if plan == "trial":
            billing, currency = _resolve_variant("Starter", "monthly", preferred)
        else:
            billing, currency = _resolve_variant(plan, billing, preferred)

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

    # Largest month at which any scheduled change/reactivation lands.
    # Once the clock is past it the cohort is in its final shape, so a
    # later Chargebee time-travel timeout (intermittent, see
    # ``TimeTravelBacklog``) is cosmetic — only steady-state renewals
    # remain — and we can stop gracefully instead of failing the run.
    last_change_month = max(
        [int(m) for e in entries for m in (e.get("change_month"), e.get("reactivate_month")) if m]
        + [0]
    )

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
                target_currency = str(entry.get("currency", "USD"))
                tb, tc = _resolve_variant("Professional", "monthly", target_currency)
                change_sub_plan(sub_id, plan="Professional", billing=tb, currency=tc)
                entry["plan"] = "Professional"
                entry["billing"] = tb
                entry["currency"] = tc
            elif action == "downgrade":
                target_currency = str(entry.get("currency", "USD"))
                tb, tc = _resolve_variant("Starter", "monthly", target_currency)
                change_sub_plan(sub_id, plan="Starter", billing=tb, currency=tc)
                entry["plan"] = "Starter"
                entry["billing"] = tb
                entry["currency"] = tc
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
        try:
            travel_forward(target)
        except TimeTravelBacklog as exc:
            if month >= last_change_month:
                print(
                    f"\nWARN: Chargebee aborted the hop to {current.date()} "
                    f"(time-travel job limit: {exc}).\n"
                    "All lifecycle changes were already applied earlier in the "
                    "window, so the seeded data is complete — stopping the "
                    "calendar advance here. Re-run the seed if you need the "
                    "clock at the present day (it's intermittent and usually "
                    "clears on a fresh run).",
                    file=sys.stderr,
                )
                break
            # Failed before the cohort was fully shaped — the data would be
            # incomplete, so surface it.
            raise RuntimeError(
                f"Time travel hit Chargebee's job limit at {current.date()} "
                f"(month {month}), before all scheduled changes "
                f"(through month {last_change_month}) were applied. "
                "Re-run the seed (start_afresh replays from scratch)."
            ) from exc
        # Small breather between travels — Chargebee occasionally
        # queues webhook deliveries and pushing through too fast can
        # cause the Funnel tunnel to fall behind.
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
