# Development

> How to set up a local development environment.

## Prerequisites

- **Docker** — PostgreSQL and Redpanda run in containers
- **Node.js 22+** — frontend build tooling
- **Stripe CLI** — webhook forwarding (`brew install stripe/stripe-cli/stripe && stripe login`)
- **uv** — Python package manager (the project uses `uv` for dependency management)
- **STRIPE_API_KEY** — test mode key (`sk_test_...`) from the [Stripe Dashboard](https://dashboard.stripe.com/test/apikeys)

**Optional (for authentication):**

- **Clerk account** — sign up at [clerk.com](https://clerk.com), create an application, and copy the API keys from the [Clerk Dashboard](https://dashboard.clerk.com)

## Quick Start

```bash
# 1. Install backend + frontend dependencies
make install-dev

# 2. Seed test data into PostgreSQL (one-time, data persists across restarts)
export STRIPE_API_KEY=sk_test_...
make seed

# 3. Start infrastructure + webhook forwarding
make dev

# 4. Start API server (separate terminal)
TIDEMILL_DATABASE_URL=postgresql+asyncpg://tidemill:test@localhost:5432/tidemill \
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
AUTH_ENABLED=false \
uv run uvicorn tidemill.api.app:app --port 8000 --reload

# 5. Start frontend dev server (separate terminal)
make frontend
```

The API is at `http://localhost:8000`, the frontend at `http://localhost:5173`. The frontend dev server proxies `/api/*` and `/auth/*` requests to the API automatically.

`make seed` runs a self-contained pipeline that starts the full stack in Docker, seeds Stripe test data via Test Clocks, processes all webhook events, and then stops. The seeded data remains in the PostgreSQL Docker volume, so `make dev` picks it up immediately. You only need to re-seed if you run `make dev-reset` (which deletes volumes). See [Testing](testing.md) for details on the seed script and what data it creates.

## What `make dev` Does

Starts infrastructure services in Docker and a background `stripe listen` process:

| Service    | Port  | Description              |
|------------|-------|--------------------------|
| PostgreSQL | :5432 | `tidemill` database      |
| Redpanda   | :9092 | Kafka-compatible broker  |

Additionally, `stripe listen` runs in the background, forwarding Stripe webhook events to `http://localhost:8000/api/webhooks/stripe`. Its PID is written to `/tmp/stripe-listen-dev.pid` and logs go to `/tmp/stripe-listen-dev.log`.

The API, worker, and frontend are **not** started in Docker — you run them from your IDE or terminal so you get live reloading and debugger support.

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
AUTH_ENABLED=false \
uv run uvicorn tidemill.api.app:app --port 8000 --reload
```

Set `AUTH_ENABLED=false` for local development without Clerk. See [Authentication](#authentication) below to enable it.

## Running the Frontend

```bash
make frontend   # starts Vite dev server on http://localhost:5173
```

The Vite dev server proxies API calls to `localhost:8000`:

| Frontend path | Proxied to           |
|---------------|----------------------|
| `/api/*`      | `http://localhost:8000` |
| `/auth/*`     | `http://localhost:8000` |
| `/healthz`    | `http://localhost:8000` |
| `/readyz`     | `http://localhost:8000` |

Hot module replacement is enabled — save a `.tsx` file and the browser updates instantly.

### Frontend Stack

| Library             | Purpose                                |
|---------------------|----------------------------------------|
| Vite + React 19     | Build tooling + UI framework           |
| TypeScript          | Type safety                            |
| React Router v7     | Client-side routing                    |
| TanStack Query v5   | Server state, caching, data fetching   |
| Tremor              | Charts (LineChart, BarChart) + UI cards |
| Tailwind CSS v4     | Utility CSS                            |
| Clerk (`@clerk/react`) | Authentication (Google SSO, etc.)   |

## Authentication

Authentication uses [Clerk](https://clerk.com). Clerk handles sign-in/sign-up entirely on the frontend. The backend verifies Clerk session JWTs.

### Developing Without Auth

Set `AUTH_ENABLED=false` on the API server. The frontend detects this via `GET /auth/config` and skips the login flow. No Clerk account needed.

### Enabling Auth Locally

1. Create a Clerk application at [dashboard.clerk.com](https://dashboard.clerk.com)
2. Enable Google (or any OAuth provider) under **User & Authentication > Social connections**
3. Copy your keys

**Frontend** — create `frontend/.env.local`:

```bash
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
```

**Backend** — add to your API server environment:

```bash
AUTH_ENABLED=true
CLERK_SECRET_KEY=sk_test_...
CLERK_JWKS_URL=https://your-app.clerk.accounts.dev/.well-known/jwks.json
```

The JWKS URL is on the Clerk Dashboard under **API Keys > Advanced > JWKS Public Key URL**.

### How Auth Works

1. Frontend wraps the app in `<ClerkProvider>` (in `main.tsx`) — reads `VITE_CLERK_PUBLISHABLE_KEY` from environment
2. Unauthenticated users see `<SignInButton>` / `<SignUpButton>` via Clerk's `<Show>` component
3. After sign-in, Clerk provides a session JWT
4. The API client (`src/api/client.ts`) attaches the JWT as `Authorization: Bearer <token>` to every request
5. The backend verifies the JWT against Clerk's JWKS endpoint
6. A local `app_user` row is upserted (keyed by Clerk user ID) for dashboard/chart ownership

### API Keys (Programmatic Access)

Users can create API keys at `/settings/api-keys` in the frontend. API keys authenticate via `Authorization: Bearer tk_...` and bypass Clerk JWT verification.

API key management itself requires Clerk authentication (not API key auth) — a compromised key cannot create more keys.

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

## Database Backup and Restore

Backup the PostgreSQL database to a file before re-seeding or making destructive changes. Backups are stored in `deploy/backup/` (gitignored).

### Backup

```bash
cd deploy/compose
docker compose exec -T postgres pg_dump -U tidemill --format=custom tidemill \
  > ../backup/tidemill_$(date +%Y-%m-%d).dump
```

### Restore

```bash
cd deploy/compose
docker compose cp ../backup/tidemill_2026-04-16.dump postgres:/tmp/restore.dump
docker compose exec postgres pg_restore -U tidemill --clean --if-exists -d tidemill /tmp/restore.dump
docker compose exec postgres rm /tmp/restore.dump
```

`--clean --if-exists` drops existing objects before recreating them, so the database returns to the exact state captured in the dump.

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

### Backend (API Server)

| Variable                   | Required | Default            | Description                                                 |
|----------------------------|----------|--------------------|-------------------------------------------------------------|
| `TIDEMILL_DATABASE_URL`    | Yes      | —                  | PostgreSQL connection string (asyncpg)                      |
| `KAFKA_BOOTSTRAP_SERVERS`  | Yes      | `localhost:9092`   | Kafka/Redpanda address                                      |
| `STRIPE_API_KEY`           | Yes      | —                  | Stripe test mode key (`sk_test_...`)                        |
| `STRIPE_WEBHOOK_SECRET`    | No       | —                  | Webhook signing secret (`whsec_...`)                        |
| `AUTH_ENABLED`             | No       | `true`             | Set `false` to disable auth entirely                        |
| `CLERK_SECRET_KEY`         | If auth  | —                  | Clerk secret key (`sk_test_...`)                            |
| `CLERK_JWKS_URL`           | If auth  | —                  | Clerk JWKS URL for JWT verification                         |
| `CORS_ORIGINS`             | No       | `http://localhost:5173` | Comma-separated allowed origins                        |
| `TIDEMILL_CONNECTOR`       | No       | `stripe`           | Connector type: `stripe`, `lago`, or `killbill`             |

### Frontend

| Variable                       | Required | Description                           |
|--------------------------------|----------|---------------------------------------|
| `VITE_CLERK_PUBLISHABLE_KEY`   | If auth  | Clerk publishable key (`pk_test_...`) |

Set in `frontend/.env.local` (not committed to git).

## Make Targets

| Target              | Description                                          |
|---------------------|------------------------------------------------------|
| `make install`      | Install backend dependencies (`uv sync --frozen`)    |
| `make install-dev`  | Install backend + frontend deps, pre-commit, git hooks |
| `make lint`         | Run ruff linter and format check                     |
| `make test`         | Run unit tests                                       |
| `make typecheck`    | Run mypy                                             |
| `make check`        | Run all checks (lint + test + typecheck)             |
| `make check-integration` | Run integration tests (starts PostgreSQL in Docker) |
| `make frontend`     | Start frontend Vite dev server on :5173              |
| `make frontend-build` | Build frontend for production                      |
| `make dev`          | Start infrastructure + stripe listen                 |
| `make dev-down`     | Stop infrastructure                                  |
| `make dev-reset`    | Stop infrastructure + delete volumes                 |
| `make seed`         | Seed Stripe test data                                |
| `make docs`         | Start MkDocs dev server on :8001                     |
