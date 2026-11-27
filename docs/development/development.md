# Development

> How to set up a local development environment.

## Prerequisites

- **Docker** — PostgreSQL and Redpanda run in containers
- **Node.js 24+** — frontend build tooling
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
TIDEMILL_DATABASE_URL=postgresql+asyncpg://tidemill:test@localhost:5434/tidemill \
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
AUTH_ENABLED=false \
uv run uvicorn tidemill.api.app:app --port 8000 --reload

# 5. Start frontend dev server (separate terminal)
make frontend
```

The API is at `http://localhost:8000`, the frontend at `http://localhost:5173`. The frontend dev server proxies `/api/*` and `/auth/*` requests to the API automatically.

`make seed` runs a self-contained pipeline that starts the full stack in Docker, seeds Stripe test data via Test Clocks, processes all webhook events, and then stops. The seeded data remains in the PostgreSQL Docker volume, so `make dev` picks it up immediately. You only need to re-seed if you run `make dev-reset` (which deletes volumes). See [Testing](testing.md) for details on the seed script and what data it creates.

## What `make dev` Does

Starts infrastructure + observability services in Docker and a background `stripe listen` process:

| Service        | Port   | Description                                      |
|----------------|--------|--------------------------------------------------|
| PostgreSQL     | :5434  | `tidemill` database                              |
| Redpanda       | :9092  | Kafka-compatible broker                          |
| OTEL Collector | :4317  | OTLP gRPC receiver (traces + metrics)            |
| Grafana        | :3000  | Observability UI — traces, logs, metrics         |

Additionally, `stripe listen` runs in the background, forwarding Stripe webhook events to `http://localhost:8000/api/webhooks/stripe`. Its PID is written to `/tmp/stripe-listen-dev.pid` and logs go to `/tmp/stripe-listen-dev.log`.

The API, worker, and frontend are **not** started in Docker — you run them from your IDE or terminal so you get live reloading and debugger support.

### Docker Compose Overlays

`make dev` chains three compose files on top of the base `docker-compose.yml`:

- `docker-compose.observability.yml` — Tempo, Loki, Prometheus, OTEL Collector, Alloy, Grafana
- `docker-compose.dev.yml` — exposes PostgreSQL/Redpanda/OTEL/Grafana on host ports; disables api/worker/caddy (you run them locally)
- Re-advertises Redpanda on `localhost` (instead of the container hostname)

For comparison, `make seed` uses `docker-compose.local.yml` which runs the full stack (API + worker) inside Docker — see [Testing](testing.md).

### Observability

Grafana is available at [http://localhost:3000](http://localhost:3000). Log in as `admin` with `GRAFANA_ADMIN_PASSWORD` from `deploy/compose/.env`. Tempo, Loki, and Prometheus are pre-provisioned as datasources.

Trace + metric export from the host-run API/worker is **on by default** — `.env.example` sets `TIDEMILL_OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317`, which `direnv` exports into your shell via `.envrc`. Set `TIDEMILL_OTEL_ENABLED=false` in `.env` to opt out.

Logs from containers are scraped by Alloy and shipped to Loki. Host-run API/worker logs reach Loki only when you pipe them through `scripts/ship-to-loki.py`:

```bash
uv run uvicorn tidemill.api.app:app --host 0.0.0.0 --port 8000 --reload 2>&1 \
    | scripts/ship-to-loki.py --service tidemill-api

uv run python -m tidemill.worker 2>&1 \
    | scripts/ship-to-loki.py --service tidemill-worker
```

The wrapper tees stdin to your terminal (so reload messages etc. stay visible) and POSTs batches to Loki's push API at `http://localhost:3100`. It extracts `trace_id` / `span_id` / log level into labels, so trace→log correlation in Grafana works for host-run processes the same way it does for containerized services. Without the pipe, the `trace_id=<hex>` prefix on your terminal still lets you paste the ID into Grafana → Tempo manually.

#### Editing dashboards

Dashboards live as JSON in `deploy/compose/observability/grafana/dashboards/`. Grafana loads them on container start and re-reads the directory every 30 seconds, so edits on disk show up live.

The workflow to persist UI edits to git:

```bash
# 1. Edit the dashboard in Grafana, then Save (Ctrl-S). The change is written to
#    Grafana's embedded DB, not to the JSON files.

# 2. Preview the drift between the live Grafana and what's committed.
make dashboards-diff

# 3. Pull the edits into the JSON files and commit them.
make dashboards-pull
git add deploy/compose/observability/grafana/dashboards/
git commit -m "dashboards: <what changed>"
```

The pull script authenticates as `admin` using `GRAFANA_ADMIN_PASSWORD` (default `admin`), normalizes Grafana's JSON (strips `id`/`version` churn), and writes one file per dashboard named after its title. Run it against a non-local Grafana by setting `GRAFANA_URL` / `GRAFANA_USER` / `GRAFANA_ADMIN_PASSWORD`.

For comparison, `make seed` uses `docker-compose.local.yml` which runs the full stack (API + worker) inside Docker — see [Testing](testing.md).

## Running the API and Worker

### From VS Code

Press **F5** to launch the API with the debugger attached (uses the workspace launch configuration).

### From the Terminal

```bash
# API server (with live reload)
TIDEMILL_DATABASE_URL=postgresql+asyncpg://tidemill:test@localhost:5434/tidemill \
KAFKA_BOOTSTRAP_SERVERS=localhost:9092 \
AUTH_ENABLED=false \
uv run uvicorn tidemill.api.app:app --port 8000 --reload
```

Set `AUTH_ENABLED=false` for local development without Clerk. See [Authentication](#authentication) below to enable it.

### Exploring the API

Once the API is running, three options for poking at it:

- **Swagger UI** at [http://localhost:8000/docs](http://localhost:8000/docs) — auto-generated from FastAPI, shows every parameter and lets you fire requests directly.
- **Bruno collection** at [`bruno/`](../../bruno/) — a folder of runnable example requests covering every endpoint (metrics, segments, attributes, dashboards, sources, webhooks). Open the folder in the Bruno desktop app, or run from the CLI:

  ```bash
  npm i -g @usebruno/cli
  cd bruno
  bru run --env Local "Metrics - MRR/02_series.bru"
  ```

  The `Local` environment defaults to `http://localhost:8000` and leaves `apiKey` blank (matches `AUTH_ENABLED=false`). See `bruno/README.md` for the full layout.
- **CLI** — `tidemill mrr`, `tidemill churn`, etc. (see [api.md](../architecture/api.md#cli-p0)).

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

`make dev` starts `stripe listen` automatically. The CLI prints its device webhook signing secret (`whsec_...`) to `/tmp/stripe-listen-dev.log`. Put it in `STRIPE_CLI_WEBHOOK_SECRET` (the local-only variant — `STRIPE_WEBHOOK_SECRET` is reserved for the deployed production endpoint):

```bash
# In your repo-root .env (or deploy/compose/.env when seeding via Compose):
STRIPE_CLI_WEBHOOK_SECRET=whsec_...
```

When the API runs locally via `docker-compose.local.yml`, the override remaps `STRIPE_WEBHOOK_SECRET` inside the container to this value so signature verification succeeds.

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
| `STRIPE_WEBHOOK_SECRET`    | No       | —                  | Production webhook endpoint signing secret (`whsec_...`)    |
| `STRIPE_CLI_WEBHOOK_SECRET`| No       | —                  | `stripe listen` device secret — used by `make seed` / local Compose to override `STRIPE_WEBHOOK_SECRET` inside the API container |
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
