# Testing

> How to generate realistic subscription data for development and testing.
> Last updated: March 2026

## Overview

Every Stripe account has a **test mode** with a separate `sk_test_` API key. Test mode data is completely isolated from live data — no real charges, no real customers.

Stripe's **Test Clocks** let you simulate time advancement: create subscriptions in the past and fast-forward through months of billing cycles, generating real invoices, renewals, cancellations, and webhook events. This is the primary way to exercise the full event pipeline.

## Prerequisites

```bash
# Stripe CLI (for webhook forwarding)
brew install stripe/stripe-cli/stripe
stripe login

# Python SDK (for the seed script)
pip install stripe
```

Get your test API key from the [Stripe Dashboard](https://dashboard.stripe.com/test/apikeys):

```bash
export STRIPE_API_KEY=sk_test_...
```

## Quick Start (3 minutes)

```bash
# Terminal 1: Start the app
cd deploy/compose
docker compose up -d

# Terminal 2: Forward Stripe webhooks to local server
stripe listen --forward-to localhost:8000/api/webhooks/stripe
# Note the whsec_... signing secret printed at startup

# Terminal 3: Seed test data
cd deploy/seed
python stripe_seed.py --customers 10 --months 3
```

The seed script creates customers, subscriptions, and advances time through 3 months of billing. Stripe fires webhook events for every invoice, payment, and renewal — the CLI forwards them to your local server.

## Seed Script

[`deploy/seed/stripe_seed.py`](https://github.com/ondraz/subscriptions/tree/main/deploy/seed/stripe_seed.py) generates a realistic dataset using Stripe Test Clocks.

### What It Creates

| Archetype | Count | Behavior |
|-----------|-------|----------|
| Active monthly customers | 4 | Normal renewals, multiple plans |
| Active annual customers | 2 | Annual billing cycle |
| Churned customers | 2 | Cancel at period end in month 2 |
| Upgraded customers | 2 | Starter → Professional in month 2 (expansion MRR) |
| Downgraded customer | 1 | Professional → Starter in month 2 (contraction MRR) |
| Failed payment customers | 2 | Card always declines (involuntary churn) |
| Trial → converted | 1 | 14-day trial, converts to paid |
| Trial → expired | 1 | 14-day trial, no conversion |

### Three Plans

| Plan | Monthly | Annual |
|------|---------|--------|
| Starter | $29 | $290 |
| Professional | $79 | $790 |
| Enterprise | $249 | $2,490 |

### Usage

```bash
# Default: 15 customers, 6 months of history
python stripe_seed.py

# Smaller dataset for quick testing
python stripe_seed.py --customers 5 --months 2

# Cleanup: delete the test clock and all its data
python stripe_seed.py --cleanup clock_...
```

### Events Generated

As time advances through each billing cycle, Stripe fires:

1. `invoice.created` — draft invoice generated
2. `invoice.finalized` — invoice finalized for payment
3. `charge.succeeded` / `payment_intent.succeeded` — payment completed
4. `invoice.paid` — invoice marked paid
5. `customer.subscription.updated` — new billing period

For cancellations:

- `customer.subscription.updated` — `cancel_at_period_end` set
- `customer.subscription.deleted` — subscription ended

For plan changes:

- `customer.subscription.updated` — new price, proration items
- `invoice.created` — proration invoice

For failed payments:

- `invoice.payment_failed` — charge declined
- `customer.subscription.updated` — status → `past_due`

For trials:

- `customer.subscription.created` — status `trialing`
- `customer.subscription.trial_will_end` — 3 days before trial ends
- `customer.subscription.updated` — status → `active` (converted) or `canceled` (expired)

## Stripe CLI Fixtures (Simpler Alternative)

For a quick smoke test without time advancement:

```bash
stripe fixtures deploy/seed/stripe_fixtures.json
```

This creates 3 products, 3 prices, 1 customer, and 1 active subscription. No billing history — useful for testing webhook handling on a single event.

## Webhook Forwarding

### Local Development

```bash
# Forward all events to your local server
stripe listen --forward-to localhost:8000/api/webhooks/stripe

# Filter to relevant events only
stripe listen --forward-to localhost:8000/api/webhooks/stripe \
  --events customer.created,customer.updated,customer.deleted,\
customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,\
invoice.created,invoice.paid,invoice.payment_failed,\
payment_intent.succeeded,payment_intent.payment_failed,\
charge.refunded
```

The CLI prints a temporary webhook signing secret (`whsec_...`) at startup. Set it in your `.env`:

```bash
STRIPE_WEBHOOK_SECRET=whsec_...
```

### Manual Event Triggers

```bash
# Trigger specific events (creates real test objects)
stripe trigger customer.subscription.created
stripe trigger invoice.payment_succeeded
stripe trigger invoice.payment_failed
stripe trigger customer.subscription.updated

# Tail events in real time
stripe listen --print-json

# List recent events
stripe events list --limit 20
```

## Test Cards

### Successful Payments

| Number | Brand |
|--------|-------|
| `4242 4242 4242 4242` | Visa |
| `5555 5555 5555 4444` | Mastercard |
| `3782 822463 10005` | Amex |

For all: any future expiry, any 3-digit CVC.

In the API, use `pm_card_visa` as a shortcut — no card numbers needed.

### Failing Cards

| Number | Failure |
|--------|---------|
| `4000 0000 0000 0002` | Generic decline |
| `4000 0000 0000 9995` | Insufficient funds |
| `4000 0000 0000 0069` | Expired card |
| `4000 0000 0000 0119` | Processing error |

The seed script uses `4000000000000002` for "failed payment" archetypes to simulate involuntary churn.

## Test Clocks — How They Work

A Stripe Test Clock overrides "now" for all resources attached to it:

```
Real time:  March 30, 2026 (unchanged)
Clock time: October 1, 2025 ──advance──► November 1, 2025 ──advance──► ...
```

When you advance the clock from October to November, Stripe processes everything that would have happened: invoice generation, payment attempts, subscription renewals, trial expirations. Every action fires the same webhook events as production.

```python
import stripe

# Create a clock starting 6 months ago
clock = stripe.test_helpers.TestClock.create(
    frozen_time=1727740800,  # Oct 1, 2025
    name="My test"
)

# Create a customer ON this clock
customer = stripe.Customer.create(
    name="Test",
    test_clock=clock.id,
    payment_method="pm_card_visa",
    invoice_settings={"default_payment_method": "pm_card_visa"},
)

# Create a subscription — it exists at clock time, not real time
sub = stripe.Subscription.create(
    customer=customer.id,
    items=[{"price": "price_..."}],
)

# Advance 1 month → triggers invoice + charge + renewal
stripe.test_helpers.TestClock.advance(
    clock.id,
    frozen_time=1730419200,  # Nov 1, 2025
)
```

### Cleanup

Deleting a test clock deletes **all** resources attached to it (customers, subscriptions, invoices, charges):

```bash
python deploy/seed/stripe_seed.py --cleanup clock_...
# or
stripe test_helpers test_clocks delete clock_...
```

## End-to-End Test Flow

The full loop to verify the pipeline:

```
stripe_seed.py          stripe listen              API server              Worker
      │                       │                         │                     │
      │  create customer      │                         │                     │
      │  create subscription  │                         │                     │
      │  advance clock        │                         │                     │
      │                       │                         │                     │
      │                  Stripe fires webhooks           │                     │
      │                       │                         │                     │
      │                       │  POST /api/webhooks     │                     │
      │                       ├────────────────────────►│                     │
      │                       │                         │  translate → Kafka  │
      │                       │                         ├────────────────────►│
      │                       │                         │                     │ update tables
      │                       │                         │                     │
      │                       │   GET /api/metrics/mrr  │                     │
      │                       │  ◄──────────────────────┤                     │
      │                       │   {"mrr": 1234.00}      │                     │
```

Verify metrics after seeding:

```bash
# Check MRR
curl localhost:8000/api/metrics/mrr

# Check MRR time series
curl "localhost:8000/api/metrics/mrr?start=2025-10-01&end=2026-03-30&interval=month"

# Check churn
curl "localhost:8000/api/metrics/churn?start=2025-12-01&end=2026-01-01"

# Check all metrics
curl localhost:8000/api/metrics/summary
```

## Lago Testing (Same-Database Mode)

For same-database mode, test data lives in Lago's PostgreSQL. No Kafka or webhooks are involved.

### Approach

1. **Use Lago's own test environment** — create customers, subscriptions, and invoices through Lago's API or UI
2. **Point the analytics engine at Lago's database** — set `CONNECTOR=lago` and `DATABASE_URL` to Lago's PostgreSQL
3. **Query metrics directly** — the analytics engine reads Lago's tables at request time

```bash
# After populating Lago with test data:
export SUBSCRIPTIONS_DATABASE_URL=postgresql://lago:password@localhost/lago
export SUBSCRIPTIONS_CONNECTOR=lago

subscriptions mrr
subscriptions churn --start 2025-12-01 --end 2026-01-01
subscriptions summary
```

No seed script is provided for Lago — use Lago's own API to create test data. The analytics engine is read-only against Lago's tables.
