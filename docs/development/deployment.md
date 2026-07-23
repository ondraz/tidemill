# Deployment

> Infrastructure as Code for single-server and Kubernetes deployments on Hetzner.

All deployment files live in [`deploy/`](https://github.com/ondraz/tidemill/tree/main/deploy):

```
deploy/
├── compose/                          # Docker Compose (shared by both deployment modes)
│   ├── docker-compose.yml
│   ├── Dockerfile                    # Multi-stage: Node (frontend) + Python (backend)
│   ├── Caddyfile                     # Serves landing + app + proxies API
│   └── .env.example
├── landing/                          # Static landing page served on the root domain
│   ├── index.html
│   └── favicon.svg
├── seed/                             # Stripe test data generation
│   ├── stripe_seed.py
│   └── stripe_fixtures.json
└── terraform/
    ├── .gitignore
    ├── single-server/                # Option A: one Hetzner server
    │   ├── main.tf
    │   ├── variables.tf
    │   ├── server.tf
    │   ├── firewall.tf
    │   ├── dns.tf
    │   ├── outputs.tf
    │   ├── cloud-init.yml
    │   └── terraform.tfvars.example
    └── kubernetes/                   # Option B: k3s cluster
        ├── main.tf
        ├── variables.tf
        ├── cluster.tf
        ├── dns.tf
        ├── app.tf
        ├── outputs.tf
        └── terraform.tfvars.example
```

## Deployment Modes

The deployment depends on which [connector type](../architecture/connectors.md) is used:

### Full Deployment (Stripe / Ingestion Mode) — Primary

For Stripe (and any webhook-based connector), the full stack is required: PostgreSQL + Kafka/Redpanda + API + Worker + Caddy (frontend). See Option A (single server) or Option B (Kubernetes) below.

**Startup ordering.** The API process owns schema creation (`create_all` runs in its lifespan and only then does `/healthz` pass). The worker waits for the API to be healthy (Compose `depends_on: api: service_healthy`) before bootstrapping its `connector_source` rows, and also retries that bootstrap in code if the table is briefly missing. This avoids the cold-start race — e.g. right after `make prod-reset` — where the worker would otherwise crash with `relation "connector_source" does not exist`.

---

### Lago Companion Mode (Same-Database)

For Lago or Kill Bill users, the analytics engine can run alongside the billing engine with **no additional infrastructure**:

```
┌────────────────────────────────────┐
│  Existing Lago deployment          │
│  ┌──────────┐  ┌────────────────┐  │
│  │  Lago    │  │  PostgreSQL    │  │
│  │  (API)   │  │  (shared)      │  │
│  └──────────┘  └───────┬────────┘  │
│                        │           │
│  ┌─────────────────────┴────────┐  │
│  │  tidemill                    │  │
│  │  (analytics CLI / API)       │  │
│  │  No Kafka. No worker.        │  │
│  └──────────────────────────────┘  │
└────────────────────────────────────┘
```

**Services:** Just the `tidemill` container (or `pip install tidemill` directly). Connects to the billing engine's PostgreSQL.

**No Kafka, no worker process, no event bus.** The analytics engine queries billing tables directly at request time.

```yaml
# docker-compose.yml addition for existing Lago deployment
services:
  analytics:
    image: ghcr.io/ondraz/tidemill:latest
    environment:
      DATABASE_URL: postgresql://lago:password@postgres/lago
      CONNECTOR: lago
    ports:
      - "8000:8000"
```

Or simply install and use the CLI:

```bash
pip install tidemill
export TIDEMILL_DATABASE_URL=postgresql://lago:password@postgres/lago
export TIDEMILL_CONNECTOR=lago

tidemill mrr
# $12,450.00
```

---

## Docker Image

The Dockerfile is a **multi-stage build**:

1. **Stage 1 (Node 22):** Builds the React frontend — `npm ci && npm run build` produces static assets in `dist/`
2. **Stage 2 (Python 3.13):** Installs the Python backend via `uv`, copies the built frontend to `/srv/frontend`

Caddy serves three things:

- **Root domain** (`tidemill.xyz`) — the static landing page from `/srv/landing` (bind-mounted from `deploy/landing/`). No API routes — the root is brochure-only.
- **`app.` subdomain** — the React dashboard from `/srv/frontend` (the Docker volume populated by the API container), plus all FastAPI routes (`/api/*`, `/auth/*`, `/healthz`, `/readyz`, `/docs`, `/openapi.json`). Same-origin, so the SPA needs no CORS. **Webhooks (Stripe, QuickBooks) and OAuth callbacks must point at `https://app.<DOMAIN>/…`.**

## Environment Variables for Production

### `deploy/compose/.env`

Copy from `deploy/compose/.env.example` and fill in:

| Variable               | Required | Description                                                    |
|------------------------|----------|----------------------------------------------------------------|
| `POSTGRES_PASSWORD`    | Yes      | PostgreSQL password (no default — must be set)                 |
| `DOMAIN`               | Yes      | Domain for Caddy TLS (e.g. `tidemill.xyz`)                    |
| `STRIPE_API_KEY`       | No       | Stripe live key (`sk_live_...`)                                |
| `STRIPE_WEBHOOK_SECRET`| No       | Production webhook endpoint signing secret (Stripe Dashboard → Webhooks → endpoint) |
| `AUTH_ENABLED`         | No       | `true` (default) or `false` to disable auth                   |
| `CLERK_PUBLISHABLE_KEY`| If auth  | Clerk publishable key (`pk_live_...`)                          |
| `CLERK_SECRET_KEY`     | If auth  | Clerk secret key (`sk_live_...`)                               |
| `CLERK_JWKS_URL`       | If auth  | Clerk JWKS URL for JWT verification                            |

### Clerk Setup for Production

1. Create a **production instance** in Clerk Dashboard (not development)
2. Set the allowed origins to your domain (e.g. `https://tidemill.xyz`)
3. Configure OAuth providers (Google, GitHub, etc.) under **User & Authentication > Social connections**
4. Copy the **live** keys (`pk_live_...`, `sk_live_...`) to your `.env`
5. The JWKS URL format is `https://your-app.clerk.accounts.dev/.well-known/jwks.json`

The frontend reads `VITE_CLERK_PUBLISHABLE_KEY` at build time. In the Docker build, this is baked into the static assets. Set it as a build arg or in the Dockerfile if needed. The default Docker Compose setup passes `CLERK_PUBLISHABLE_KEY` to the API container — the frontend must be rebuilt if the key changes.

---

## Option A: Single Server

A single Hetzner CX22 (2 vCPU, 4 GB RAM, ~€4/mo) running Docker Compose. Good for getting started, small-to-medium workloads, or development.

### What Terraform Provisions

| Resource | Purpose |
|----------|---------|
| `hcloud_server` | Ubuntu 24.04 with Docker (via cloud-init) |
| `hcloud_ssh_key` | Your SSH key for server access |
| `hcloud_firewall` | Allows only SSH, HTTP, HTTPS, ICMP inbound |
| `hcloud_zone_rrset` | A + AAAA DNS records pointing to the server |

### Services (Docker Compose)

| Container | Role | RAM |
|-----------|------|-----|
| **Caddy** | Reverse proxy, auto-HTTPS, serves frontend | ~20 MB |
| **API** | FastAPI — metrics, webhooks, auth, dashboards | ~100 MB |
| **Worker** | Kafka consumers — core state + metrics | ~150 MB |
| **Redpanda** | Kafka-compatible bus (no JVM, no ZooKeeper) | ~256 MB |
| **PostgreSQL** | Primary database | ~256 MB |

Total: **~800 MB**. Fits on CX22 with headroom.

### Caddy Configuration

Caddy splits the deployment into the public landing page (root domain, brochure-only) and the React dashboard + API (`app.` subdomain). All FastAPI routes — including webhooks and OAuth callbacks — are served from the `app.` subdomain only:

```
{$DOMAIN:localhost} {
    root * /srv/landing
    try_files {path} /index.html
    file_server
}

app.{$DOMAIN:localhost} {
    handle /api/*        { reverse_proxy api:8000 }
    handle /auth/*       { reverse_proxy api:8000 }
    handle /healthz      { reverse_proxy api:8000 }
    handle /readyz       { reverse_proxy api:8000 }
    handle /docs         { reverse_proxy api:8000 }
    handle /openapi.json { reverse_proxy api:8000 }

    handle {
        root * /srv/frontend
        try_files {path} /index.html    # SPA fallback
        file_server
    }
}
```

The `try_files` directive sends all non-file paths to `index.html`, enabling React Router's client-side routing. **Webhook and OAuth-callback URLs must use the `app.` subdomain** — e.g. `https://app.tidemill.xyz/api/webhooks/stripe`, `https://app.tidemill.xyz/api/webhooks/quickbooks`, `https://app.tidemill.xyz/api/connectors/quickbooks/oauth/callback`.

### Quickstart

```bash
# 1. Prerequisites
brew install terraform   # or apt install terraform

# 2. Configure secrets
cd deploy/terraform/single-server
cp .env.example .env
# Edit .env: set TF_VAR_hcloud_token, TF_VAR_tailscale_auth_key

# 3. Configure Clerk + Stripe
cd ../../compose
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, DOMAIN, CLERK_*, STRIPE_* keys

# 4. Deploy
cd ../terraform/single-server
set -a && source .env && set +a
terraform init
terraform plan     # review what will be created
terraform apply    # provision server, firewall, DNS zone

# 5. Set nameservers at your domain registrar
terraform output nameservers
# → Set these as custom nameservers for tidemill.xyz at your registrar

# 6. Verify (wait ~2 min for cloud-init + DNS propagation)
curl https://app.tidemill.xyz/healthz

# 7. Open the public landing page
open https://tidemill.xyz

# 8. Open the React dashboard
open https://app.tidemill.xyz
```

### What cloud-init Does

The server bootstraps itself on first boot via [`cloud-init.yml`](https://github.com/ondraz/tidemill/tree/main/deploy/terraform/single-server/cloud-init.yml):

1. Updates packages and installs Docker
2. Clones the repo to `/opt/tidemill`
3. Generates a random Postgres password
4. Generates a random Grafana admin password (via Terraform `random_password`)
5. Starts Docker Compose with both `docker-compose.yml` and `docker-compose.observability.yml`
6. Enables unattended security updates
7. Reboots if the kernel was updated

### Deploying a New Version

Production deploys are driven by [`scripts/deploy-remote.sh`](https://github.com/ondraz/tidemill/blob/main/scripts/deploy-remote.sh), invoked through the `make deploy` target. The script SSHes to the server over Tailscale, checks out the requested ref in `/opt/tidemill`, then rebuilds and recreates the Compose stack.

**From CI (recommended):** the [`Deploy to Hetzner`](https://github.com/ondraz/tidemill/blob/main/.github/workflows/deploy.yml) workflow runs on three triggers:

- Pushing a `release-*` tag (e.g. `git tag release-2026-05-18 && git push --tags`).
- Publishing a GitHub Release — the release's tag is deployed.
- Manual `workflow_dispatch` with a ref input (any branch, tag, or SHA).

The workflow authenticates to Tailscale via the `TS_OAUTH_CLIENT_ID` / `TS_OAUTH_SECRET` repo secrets and then runs `make deploy DEPLOY_REF=<ref>`.

**From your laptop** (you must be connected to the `tidemill` Tailnet):

```bash
make deploy                          # deploys the current tag, or HEAD if untagged
make deploy DEPLOY_REF=release-2026-05-18
make deploy DEPLOY_SERVER=tidemill@tidemill DEPLOY_REF=main
```

### Observability

OpenTelemetry is enabled by default. The server runs a self-contained Grafana stack:

| Service        | Exposure        | Purpose                                         |
|----------------|-----------------|-------------------------------------------------|
| OTEL Collector | internal only   | OTLP receiver, forwards to Tempo and Prometheus |
| Tempo          | internal only   | Trace storage (24 h retention)                  |
| Loki           | internal only   | Log storage (7 d retention)                     |
| Prometheus     | internal only   | Metrics storage (15 d retention)                |
| Alloy          | internal only   | Scrapes Docker container logs → Loki           |
| Grafana        | `grafana.<domain>` | Web UI (TLS via Caddy + Let's Encrypt)         |

Fetch the Grafana admin password after `terraform apply`:

```bash
terraform output -raw grafana_admin_password
```

Open `https://grafana.<domain>` and log in as `admin`. Tempo, Loki, and Prometheus are pre-provisioned as datasources; the `Tidemill Overview` dashboard shows RED metrics for the API and worker.

Disable the stack by setting `TIDEMILL_OTEL_ENABLED=false` in `.env` and restarting the api + worker containers (the observability services themselves can be left running or stopped with `docker compose -f docker-compose.observability.yml stop`).

### Destroy

```bash
terraform destroy   # removes server, firewall, DNS records
```

## Option B: Kubernetes Cluster

A 3-node HA k3s cluster with separate worker nodes, running on Hetzner. For production workloads that need horizontal scaling and high availability.

### What Terraform Provisions

| Resource | Purpose |
|----------|---------|
| k3s cluster (via `kube-hetzner` module) | 3 control plane nodes + N worker nodes |
| `hcloud_load_balancer` | Ingress load balancer with public IP |
| `hcloud_zone_rrset` | DNS records pointing to the load balancer |
| `kubernetes_namespace` | `tidemill` namespace |
| `kubernetes_secret` | Database credentials, Kafka config, Clerk keys |
| `kubernetes_stateful_set` x 2 | PostgreSQL + Redpanda with Hetzner CSI volumes |
| `kubernetes_deployment` x 2 | API (2 replicas) + Worker (2 replicas) |
| `kubernetes_ingress_v1` | Traefik ingress with TLS |

### Architecture

```
                        Load Balancer (lb11)
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
          ┌─────────┐   ┌─────────┐   ┌─────────┐
          │  CP #1  │   │  CP #2  │   │  CP #3  │   Control Plane (cx22 x 3)
          │  k3s    │   │  k3s    │   │  k3s    │
          └─────────┘   └─────────┘   └─────────┘
               │              │              │
          ┌─────────┐   ┌─────────┐
          │Worker #1│   │Worker #2│   Worker Nodes (cx32 x N)
          │ API     │   │ API     │
          │ Worker  │   │ Worker  │
          │ PG      │   │ Redpanda│
          └─────────┘   └─────────┘
```

### Quickstart

```bash
# 1. Configure
cd deploy/terraform/kubernetes
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars: set hcloud_token, domain, domain_zone

# 2. Deploy (~5 min for cluster, ~2 min for app)
terraform init
terraform plan
terraform apply

# 3. Access the cluster
export KUBECONFIG=$(terraform output -raw kubeconfig_path)
kubectl get pods -n tidemill

# 4. Verify
curl https://app.tidemill.xyz/healthz
```

### Scaling

```bash
# Scale API replicas
kubectl scale deployment api -n tidemill --replicas=4

# Scale workers (Kafka rebalances partitions automatically)
kubectl scale deployment worker -n tidemill --replicas=4

# Add more Hetzner worker nodes — edit terraform.tfvars:
#   worker_count = 4
terraform apply
```

### Cost Estimate

| Component | Type | Count | Monthly |
|-----------|------|-------|---------|
| Control plane | CX22 (2 vCPU, 4 GB) | 3 | ~€12 |
| Workers | CX32 (4 vCPU, 8 GB) | 2 | ~€14 |
| Load balancer | LB11 | 1 | ~€6 |
| Volumes | 10 GB x 2 (PG + Redpanda) | 2 | ~€1 |
| **Total** | | | **~€33/mo** |

### Production Hardening

For a production Kubernetes deployment, consider:

- **Managed PostgreSQL** — replace the StatefulSet with Hetzner DBaaS or an external managed database. Remove the `kubernetes_stateful_set.postgres` resource and update `DATABASE_URL` in the secret.
- **Redpanda cluster** — replace the single-node StatefulSet with the [Redpanda Helm chart](https://github.com/redpanda-data/helm-charts) for a 3-broker cluster, or use Confluent Cloud / Amazon MSK.
- **Image registry** — push to GitHub Container Registry (`ghcr.io/ondraz/tidemill`) and pin image tags instead of `latest`.
- **Secrets management** — use [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) or [External Secrets Operator](https://external-secrets.io/) instead of plain Kubernetes secrets. Store Clerk keys and Stripe keys here.
- **Monitoring** — deploy Prometheus + Grafana via Helm for cluster and application metrics.
- **Backups** — use [Velero](https://velero.io/) for cluster backup, pg_dump CronJob for PostgreSQL.

## Compose <> Kubernetes Mapping

The Docker Compose and Kubernetes deployments use the same container images and environment variables. This table shows how each Compose concept translates:

| Docker Compose | Kubernetes | Notes |
|---------------|------------|-------|
| `postgres` service | `StatefulSet` + `PersistentVolumeClaim` | Hetzner CSI volumes |
| `redpanda` service | `StatefulSet` + `PersistentVolumeClaim` | Or Redpanda Helm chart |
| `api` service | `Deployment` + `Service` + `Ingress` | Scales horizontally |
| `worker` service | `Deployment` | Kafka rebalances partitions across replicas |
| `caddy` service | Traefik `Ingress` (built into kube-hetzner) | TLS via Let's Encrypt |
| `.env` file | `Secret` | Includes Clerk + Stripe keys |
| Docker `volumes` | `PersistentVolumeClaim` + Hetzner CSI | |
| `ports: 80, 443` | `LoadBalancer` service | Hetzner Cloud LB |
| `frontend_assets` volume | Init container or build stage | Static files served by ingress |

## Backups

### Single Server

```bash
# PostgreSQL dump (add to crontab on the server)
docker compose exec postgres pg_dump -U tidemill tidemill \
  | gzip > /opt/backups/tidemill-$(date +%F).sql.gz

# Or use Hetzner server snapshots (~€0.01/GB/mo)
```

### Kubernetes

```bash
# PostgreSQL dump via CronJob (or use Velero for full cluster backup)
kubectl exec -n tidemill postgres-0 -- \
  pg_dump -U tidemill tidemill | gzip > backup.sql.gz
```

## Why Redpanda over Apache Kafka

| Factor | Redpanda | Apache Kafka |
|--------|----------|-------------|
| Runtime | Single C++ binary | JVM + ZooKeeper (or KRaft) |
| Memory (1 broker) | ~256 MB | ~1-2 GB |
| Startup time | Seconds | 30+ seconds |
| API | Kafka-compatible | Native |
| Swap to Kafka | Zero code changes | - |

For single-server: Redpanda saves ~1 GB of RAM. For Kubernetes production: swap to the Redpanda Helm chart or a managed Kafka service with no application changes.
