# Testing

> How to generate realistic subscription data and validate the event pipeline.

## Overview

Every Stripe account has a **test mode** with a separate `sk_test_` API key. Test mode data is completely isolated from live data — no real charges, no real customers.

Stripe's **Test Clocks** let you simulate time advancement: create subscriptions in the past and fast-forward through months of billing cycles, generating real invoices, renewals, cancellations, and webhook events. This is the primary way to exercise the full event pipeline.

## Seeding Test Data

```bash
# Seed Stripe test data (self-contained — starts its own stack)
make seed   # requires STRIPE_API_KEY
```

### What `make seed` Does

1. **Cleans up** — deletes existing test clocks and their resources, stops any running stack
2. **Starts the full stack** in Docker (PostgreSQL + Redpanda + API + Worker) using `docker-compose.local.yml`
3. **Starts `stripe listen`** to forward webhook events to the API
4. **Runs the seed script** (`deploy/seed/stripe_seed.py`) — creates customers, subscriptions, and advances time through 18 months of billing cycles
5. **Validates results** — checks that sources, metrics, and MRR are populated
6. **Stops the stack** — the seeded data remains in PostgreSQL volumes

After seeding, use `make dev` to restart the infrastructure for local development (see [Development](development.md)).

### Running the Seed Script Directly

```bash
cd deploy/seed
STRIPE_API_KEY=sk_test_... python stripe_seed.py                  # full seed (19 customers, 18 months)
STRIPE_API_KEY=sk_test_... python stripe_seed.py --customers 5    # fewer customers
STRIPE_API_KEY=sk_test_... python stripe_seed.py --months 6       # shorter history
STRIPE_API_KEY=sk_test_... python stripe_seed.py --cleanup        # delete all seed clocks
STRIPE_API_KEY=sk_test_... python stripe_seed.py --cleanup CLOCK_ID  # delete specific clock
```

### Dimension Variety

The seed rotates values across several fields so dashboards have visible
breakdowns on a fresh install:

- **`customer.country`** — cycles through `US`, `GB`, `DE`, `FR`, `CA`, `AU`
  (written to `address.country`; Stripe's `customer.created` webhook carries
  it, the connector forwards it as `payload.country`, and the state consumer
  persists it in `customer.country`).
- **`currency`** — Starter-tier base prices and Enterprise monthly prices
  have `usd` / `eur` / `gbp` variants. Subscriptions rotate through them.
  Metered tiers stay USD-only because Stripe billing meters are
  single-currency.
- **`cancel_reason`** — every cancel operation passes
  `cancellation_details.feedback` (`too_expensive`, `missing_features`,
  `switched_service`, `customer_service`, `unused`, `low_quality`, `other`);
  the connector forwards it so it surfaces on `metric_churn_event.cancel_reason`.

Plan/product dimensions (`plan_interval`, `plan_name`, `product_name`, …)
are declared on the cubes but are not populated yet — the Stripe connector
does not emit `plan.*` / `product.*` events, so `subscription.plan_id`
stays NULL and joins through `plan` return empty.

## Running Tests

### Unit Tests

```bash
make test                # runs pytest (excludes integration tests)
make check               # runs lint + test + typecheck
```

Unit tests use an in-memory SQLite database (via `aiosqlite`) — no Docker or PostgreSQL required.

### Integration Tests

```bash
make check-integration   # starts a PostgreSQL container, runs integration tests, cleans up
```

This starts a temporary PostgreSQL container on port 5433, runs tests marked `@pytest.mark.integration`, and removes the container afterward.

### Frontend Type-Checking

```bash
cd frontend
npm run build            # runs tsc -b && vite build (type errors fail the build)
```

There is no separate `tsc --noEmit` target — the `build` command runs the TypeScript compiler first.

## Plans

All plans use usage-based billing via Stripe Billing Meters (`analytical_query` events):

| Plan         | Base Fee                  | Metered Component                        |
|--------------|---------------------------|------------------------------------------|
| Starter      | $20/mo                    | $1 per query                             |
| Professional | $79/mo / $790/yr          | 10,000 queries free, then $0.01/query    |
| Enterprise   | $249/mo / $2,490/yr       | Unlimited (flat fee)                     |
| Trial        | 30-day free               | Converts to Starter billing              |

## Customer Archetypes

The seed script creates 19 customers by default across these archetypes:

| Archetype                | Plan         | Billing | Behavior                                  | Queries/mo |
|--------------------------|--------------|---------|-------------------------------------------|------------|
| Active Starter (x2)      | Starter      | Month   | Normal renewals                            | 30-50      |
| Active Starter Heavy     | Starter      | Month   | High usage                                 | 120        |
| Active Monthly Pro (x2)  | Professional | Month   | Normal renewals                            | 8k-15k     |
| Active Annual Pro        | Professional | Year    | Annual billing                             | 12k        |
| Active Annual Enterprise | Enterprise   | Year    | Flat fee, no metered usage                 | --         |
| Churned Starter          | Starter      | Month   | Cancels at period end in month 2           | 20         |
| Churned Pro              | Professional | Month   | Cancels at period end in month 2           | 9k         |
| Upgraded (x2)            | Starter      | Month   | Upgrades to Professional in month 2        | 60-80      |
| Downgraded               | Professional | Month   | Downgrades to Starter in month 2           | 2k         |
| Failed Payment           | Starter      | Month   | Card always declines (involuntary churn)   | 40         |
| Trial → Converted        | Trial        | Month   | 30-day trial, converts to paid Starter     | 25         |
| Trial → Expired          | Trial        | Month   | 30-day trial, cancelled before conversion  | --         |

### Monthly Trial Additions

Beyond the initial 19 customers, the script adds **2-5 new trial customers each month** (except the last month). Some convert to Starter and some churn, producing realistic month-over-month growth patterns.

### Customer Attributes & Example Segments

After the webhook ingest finishes, `seed.sh` posts `deploy/seed/customer_attributes.csv` to `POST /api/attributes/import` (matched by email — seed customer emails are deterministic `seed-N@test.example.com`). That populates four attributes for the 19 archetype customers — `account_manager`, `region`, `industry`, `is_strategic` — covering data the segment builder couldn't otherwise reach via Stripe metadata. It then creates two starter segments via `POST /api/segments`:

- **Strategic accounts** — `attr.is_strategic = true`
- **EMEA region** — `attr.region = EMEA`

so a fresh stack has something for the `SegmentPicker` to bind to. Stripe-sourced attributes (`seed`, `archetype`, `country` from `customer.metadata`) land automatically via the state consumer's `fan_out_customer_metadata` call — no separate import required.

### Cleanup

Deleting a test clock deletes **all** resources attached to it (customers, subscriptions, invoices, charges):

```bash
# Via make (cleans up all clocks before re-seeding)
make seed

# Cleanup only, no re-seed
./deploy/seed/seed.sh --cleanup-only

# Or via the Python script
python deploy/seed/stripe_seed.py --cleanup
python deploy/seed/stripe_seed.py --cleanup clock_...
```

## Verifying Metrics After Seeding

Start the dev stack and API, then verify metrics via curl or the frontend:

```bash
# Check MRR
curl localhost:8000/api/metrics/mrr

# Check MRR time series
curl "localhost:8000/api/metrics/mrr?start=2025-10-01&end=2026-03-30&interval=month"

# Check MRR breakdown
curl "localhost:8000/api/metrics/mrr/breakdown?start=2025-09-01&end=2026-03-31"

# Check churn
curl "localhost:8000/api/metrics/churn?start=2025-12-01&end=2026-01-01"

# Check retention
curl "localhost:8000/api/metrics/retention?start=2025-09-01&end=2026-03-31"

# Check all metrics
curl localhost:8000/api/metrics/summary
```

Or open the frontend at `http://localhost:5173` and navigate to the report pages — MRR, Churn, Retention, LTV, Trials — all query the same API endpoints.

## Verifying the Frontend

With the API running and seeded data in PostgreSQL:

1. Start the frontend: `make frontend`
2. Open `http://localhost:5173` (with `AUTH_ENABLED=false` on the API, no login required)
3. Navigate each report page and verify charts render with data:
   - **Overview** (`/`) — KPI cards for all metrics
   - **MRR** (`/reports/mrr`) — line chart, bar breakdown, waterfall
   - **Churn** (`/reports/churn`) — logo and revenue churn rate charts
   - **Retention** (`/reports/retention`) — cohort heatmap
   - **LTV** (`/reports/ltv`) — LTV line chart
   - **Trials** (`/reports/trials`) — conversion rate chart
4. Test dashboard CRUD:
   - Create a dashboard at `/dashboards`
   - Save a chart from any report page (bookmark icon)
   - Add the saved chart to your dashboard
5. If auth is enabled, test the login flow and API key management at `/settings/api-keys`

## Events Generated

As time advances through each billing cycle, Stripe fires webhook events:

**Renewals:**

1. `invoice.created` — draft invoice generated
2. `invoice.finalized` — invoice finalized for payment
3. `charge.succeeded` / `payment_intent.succeeded` — payment completed
4. `invoice.paid` — invoice marked paid
5. `customer.subscription.updated` — new billing period

**Cancellations:**

- `customer.subscription.updated` — `cancel_at_period_end` set
- `customer.subscription.deleted` — subscription ended

**Plan changes (upgrades/downgrades):**

- `customer.subscription.updated` — new price, proration items
- `invoice.created` — proration invoice

**Failed payments:**

- `invoice.payment_failed` — charge declined
- `customer.subscription.updated` — status → `past_due`

**Trials:**

- `customer.subscription.created` — status `trialing`
- `customer.subscription.trial_will_end` — 3 days before trial ends
- `customer.subscription.updated` — status → `active` (converted) or `canceled` (expired)

## Test Clocks

A Stripe Test Clock overrides "now" for all resources attached to it:

```
Real time:  March 30, 2026 (unchanged)
Clock time: October 1, 2025 ──advance──► November 1, 2025 ──advance──► ...
```

When you advance the clock from October to November, Stripe processes everything that would have happened: invoice generation, payment attempts, subscription renewals, trial expirations, metered usage billing. Every action fires the same webhook events as production.

The seed script groups customers into test clocks with a maximum of 3 customers per clock (Stripe's limit) and advances all clocks in parallel.

## Test Cards

### Successful Payments

| Number | Brand |
|--------|-------|
| `4242 4242 4242 4242` | Visa |
| `5555 5555 5555 4444` | Mastercard |
| `3782 822463 10005` | Amex |

For all: any future expiry, any 3-digit CVC. In the API, use `pm_card_visa` as a shortcut.

### Failing Cards

| Number | Failure |
|--------|---------|
| `4000 0000 0000 0341` | Attaches OK, fails on charge (used by seed script) |
| `4000 0000 0000 0002` | Generic decline |
| `4000 0000 0000 9995` | Insufficient funds |
| `4000 0000 0000 0069` | Expired card |
| `4000 0000 0000 0119` | Processing error |

## Stripe CLI Fixtures (Quick Smoke Test)

For a quick smoke test without time advancement:

```bash
stripe fixtures deploy/seed/stripe_fixtures.json
```

This creates 3 products, 3 prices, 1 customer, and 1 active subscription. No billing history — useful for testing a single webhook handler.

## End-to-End Test Flow

The full loop to verify the pipeline:

```
stripe_seed.py          stripe listen              API server              Worker
      |                       |                         |                     |
      |  create customer      |                         |                     |
      |  create subscription  |                         |                     |
      |  advance clock        |                         |                     |
      |                       |                         |                     |
      |                  Stripe fires webhooks           |                     |
      |                       |                         |                     |
      |                       |  POST /api/webhooks     |                     |
      |                       +------------------------>|                     |
      |                       |                         |  translate -> Kafka |
      |                       |                         +-------------------->|
      |                       |                         |                     | update tables
      |                       |                         |                     |
      |                       |   GET /api/metrics/mrr  |                     |
      |                       |  <----------------------+                     |
      |                       |   {"mrr": 1234.00}      |                     |
```

## Chargebee Testing (Test Site + Time Machine)

Chargebee mirrors the Stripe flow but with a few structural differences:

- **One Time Machine, no per-customer clocks.** Chargebee's site-wide
  ``delorean`` clock advances every subscription in one call —
  ``stripe_seed.py``'s 3-customers-per-clock batching isn't needed.
- **Webhooks need a public URL.** Unlike Stripe (which has the local
  ``stripe listen`` CLI that opens a websocket tunnel), Chargebee posts
  webhooks to a configured HTTP endpoint. For local dev you need a
  tunnel from a public URL to ``localhost:8000``.

### Prerequisites

1. **Free Test Site** — sign up at chargebee.com, pick "Test Site" (not
   Production). Site name becomes the part before ``.chargebee.com``
   (e.g. ``acme-test``).
2. **Full-access TEST API key** — Settings → API Keys → "Add API Key" →
   "Full Access" → Test mode. Starts with ``test_``.
3. **Public webhook tunnel.** Two options that work locally:
   - **smee.io** (free, no signup): `npm install -g smee-client`, then
     run `smee --url https://smee.io/<your-channel> --target
     http://localhost:8000/api/webhooks/chargebee` in a separate
     terminal. Grab the channel URL from smee.io.
   - **ngrok**: `ngrok http 8000` (free tier requires an account).
4. **Configure the webhook in Chargebee** — Settings → Webhooks → "Add
   Webhook". URL is the smee/ngrok public URL plus
   ``/api/webhooks/chargebee``. Enable HTTP Basic Auth and set the same
   user/pass you put in ``CHARGEBEE_WEBHOOK_USERNAME`` /
   ``CHARGEBEE_WEBHOOK_PASSWORD``. Subscribe to at least the
   ``customer.*``, ``subscription.*``, ``invoice.*``, ``payment.*``,
   ``coupon.*``, and ``credit_note.*`` event groups.

### Environment

```bash
CHARGEBEE_SITE=acme-test
CHARGEBEE_API_KEY=test_...
CHARGEBEE_WEBHOOK_USERNAME=tidemill
CHARGEBEE_WEBHOOK_PASSWORD=change-me-locally
```

### Running the seed

```bash
# Full seed (19 customers, 18 months) against the configured Test Site
python deploy/seed/chargebee_seed.py

# Smaller / shorter runs
python deploy/seed/chargebee_seed.py --customers 5
python deploy/seed/chargebee_seed.py --months 6

# Wipe every entity tagged seed=tidemill
python deploy/seed/chargebee_seed.py --cleanup
```

The script:

1. Creates an Item Family ("tidemill"), three Items (Starter,
   Professional, Enterprise), and their currency/period Item Prices.
2. Creates customers per the archetype list, each on a subscription.
3. Travels the Time Machine forward one month at a time, applying
   scheduled lifecycle changes (churn, upgrade, downgrade, trial
   conversion, churn → reactivate) at the right months.

While the script runs, the smee/ngrok tunnel forwards Chargebee
webhooks into Tidemill where the canonical state and metric handlers
materialize MRR, churn, retention, and cohort tables.

### Cleanup

`--cleanup` deletes subscriptions, customers, item_prices, items, and
the item_family in dependency order. Best-effort: Chargebee occasionally
rejects deletes for in-flight test transactions; re-running cleanup
clears whatever stuck the first time.

## Lago Testing (Same-Database Mode)

For same-database mode, test data lives in Lago's PostgreSQL. No Kafka or webhooks are involved.

1. **Use Lago's own test environment** — create customers, subscriptions, and invoices through Lago's API or UI
2. **Point the analytics engine at Lago's database** — set `CONNECTOR=lago` and `DATABASE_URL` to Lago's PostgreSQL
3. **Query metrics directly** — the analytics engine reads Lago's tables at request time

```bash
export TIDEMILL_DATABASE_URL=postgresql://lago:password@localhost/lago
export TIDEMILL_CONNECTOR=lago

tidemill mrr
tidemill churn --start 2025-12-01 --end 2026-01-01
tidemill summary
```

No seed script is provided for Lago — use Lago's own API to create test data. The analytics engine is read-only against Lago's tables.
