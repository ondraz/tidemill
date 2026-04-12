# Development

> How to set up a local development environment.

## Prerequisites

- **Docker** — PostgreSQL and Redpanda run in containers
- **Stripe CLI** — webhook forwarding (`brew install stripe/stripe-cli/stripe && stripe login`)
- **uv** — Python package manager (the project uses `uv` for dependency management)
- **STRIPE_API_KEY** — test mode key (`sk_test_...`) from the [Stripe Dashboard](https://dashboard.stripe.com/test/apikeys)

## Quick Start

```bash
export STRIPE_API_KEY=sk_test_...

# 1. Seed test data into PostgreSQL (one-time, data persists across restarts)
make seed

# 2. Start infrastructure + webhook forwarding
make dev

# 3. Start API server (separate terminal)
TIDEMILL_DATABASE_URL=postgresql+asyncpg://tidemill:test@localhost:5432/tidemill \
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
uv run uvicorn tidemill.api.app:app --port 8000 --reload
```

`make seed` runs a self-contained pipeline that starts the full stack in Docker, seeds Stripe test data via Test Clocks, processes all webhook events, and then stops. The seeded data remains in the PostgreSQL Docker volume, so `make dev` picks it up immediately. You only need to re-seed if you run `make dev-reset` (which deletes volumes). See [Testing](testing.md) for details on the seed script and what data it creates.

## What `make dev` Does

Starts infrastructure services in Docker and a background `stripe listen` process:

| Service    | Port  | Description              |
|------------|-------|--------------------------|
| PostgreSQL | :5432 | `tidemill` database      |
| Redpanda   | :9092 | Kafka-compatible broker  |

Additionally, `stripe listen` runs in the background, forwarding Stripe webhook events to `http://localhost:8000/api/webhooks/stripe`. Its PID is written to `/tmp/stripe-listen-dev.pid` and logs go to `/tmp/stripe-listen-dev.log`.

The API and worker are **not** started in Docker — you run them from your IDE or terminal so you get live reloading and debugger support.

### Docker Compose Overlays

`make dev` uses `docker-compose.dev.yml` on top of the base `docker-compose.yml`. This overlay:

- Exposes PostgreSQL and Redpanda ports to the host
- Re-advertises Redpanda on `localhost` (instead of the container hostname)
- Disables the API, worker, and Caddy services (you run these locally)

For comparison, `make seed` uses `docker-compose.local.yml` which runs the full stack (API + worker) inside Docker — see [Testing](testing.md).

## Running the API and Worker

### From VS Code

Press **F5** to launch the API with the debugger attached (uses the workspace launch configuration).

### From the Terminal

```bash
# API server (with live reload)
TIDEMILL_DATABASE_URL=postgresql+asyncpg://tidemill:test@localhost:5432/tidemill \
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
uv run uvicorn tidemill.api.app:app --port 8000 --reload
```

## Webhook Forwarding

`make dev` starts `stripe listen` automatically. The CLI prints a temporary webhook signing secret (`whsec_...`) to `/tmp/stripe-listen-dev.log`. Set it in your environment if your webhook endpoint validates signatures:

```bash
export STRIPE_WEBHOOK_SECRET=whsec_...
```

### Manual Event Triggers

Useful for testing a single webhook handler without seeding a full dataset:

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

### Filtering Events

To forward only the events the connector handles:

```bash
stripe listen --forward-to localhost:8000/api/webhooks/stripe \
  --events customer.created,customer.updated,customer.deleted,\
customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,\
invoice.created,invoice.paid,invoice.payment_failed,\
payment_intent.succeeded,payment_intent.payment_failed,\
charge.refunded
```

## Stopping and Resetting

```bash
make dev-down    # Stop infrastructure + kill stripe listen
make dev-reset   # Stop infrastructure + delete all volumes (fresh database)
```

## Lago Companion Mode

No Docker required — install the package and point it at Lago's PostgreSQL:

```bash
pip install tidemill
export TIDEMILL_DATABASE_URL=postgresql://lago:password@postgres/lago
export TIDEMILL_CONNECTOR=lago
tidemill mrr
```

## Environment Variables

| Variable                   | Required | Description                                                 |
|----------------------------|----------|-------------------------------------------------------------|
| `STRIPE_API_KEY`           | Yes      | Stripe test mode key (`sk_test_...`)                        |
| `TIDEMILL_DATABASE_URL`    | Yes      | PostgreSQL connection string                                |
| `KAFKA_BOOTSTRAP_SERVERS`  | Yes      | Kafka/Redpanda address (default: `localhost:9092`)          |
| `STRIPE_WEBHOOK_SECRET`    | No       | Webhook signing secret (`whsec_...` from `stripe listen`)  |
| `TIDEMILL_CONNECTOR`       | No       | Connector type: `stripe` (default), `lago`, or `killbill`  |

## Other Make Targets

| Target              | Description                                          |
|---------------------|------------------------------------------------------|
| `make install`      | Install dependencies (`uv sync --frozen`)            |
| `make install-dev`  | Install dev dependencies + pre-commit + git hooks    |
| `make lint`         | Run ruff linter and format check                     |
| `make test`         | Run unit tests                                       |
| `make typecheck`    | Run mypy                                             |
| `make check`        | Run all checks (lint + test + typecheck)             |
| `make check-integration` | Run integration tests (starts PostgreSQL in Docker) |
| `make docs`         | Start MkDocs dev server on :8001                     |
