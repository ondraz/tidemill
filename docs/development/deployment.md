# Deployment

> Infrastructure as Code for single-server and Kubernetes deployments on Hetzner.
> Last updated: March 2026

All deployment files live in [`deploy/`](https://github.com/ondraz/tidemill/tree/main/deploy):

```
deploy/
├── compose/                          # Docker Compose (shared by both deployment modes)
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── Caddyfile
│   └── .env.example
└── terraform/
    ├── .gitignore                    # Excludes tfstate, tfvars, .terraform/
    ├── single-server/                # Option A: one Hetzner server
    │   ├── main.tf                   # Provider config
    │   ├── variables.tf              # Input variables
    │   ├── server.tf                 # Server + SSH key
    │   ├── firewall.tf               # Firewall rules
    │   ├── dns.tf                    # DNS A/AAAA records
    │   ├── outputs.tf                # IP, URL, SSH command
    │   ├── cloud-init.yml            # Server bootstrap script
    │   └── terraform.tfvars.example
    └── kubernetes/                   # Option B: k3s cluster
        ├── main.tf                   # Provider config
        ├── variables.tf              # Input variables
        ├── cluster.tf                # k3s cluster via kube-hetzner module
        ├── dns.tf                    # DNS pointing to load balancer
        ├── app.tf                    # K8s resources (deployments, services, ingress)
        ├── outputs.tf                # Kubeconfig path, LB IP, URL
        └── terraform.tfvars.example
```

## Deployment Modes

The deployment depends on which [connector type](connectors.md) is used:

### Full Deployment (Stripe / Ingestion Mode) — Primary

For Stripe (and any webhook-based connector), the full stack is required: PostgreSQL + Kafka/Redpanda + API + Worker. See Option A (single server) or Option B (Kubernetes) below.

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

This mode is lower priority but a strong differentiator for open-source billing engine users.

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
| **Caddy** | Reverse proxy, auto-HTTPS via Let's Encrypt | ~20 MB |
| **API** | FastAPI — metrics, webhooks | ~100 MB |
| **Worker** | Kafka consumers — core state + metrics | ~150 MB |
| **Redpanda** | Kafka-compatible bus (no JVM, no ZooKeeper) | ~256 MB |
| **PostgreSQL** | Primary database | ~256 MB |

Total: **~800 MB**. Fits on CX22 with headroom.

### Quickstart

```bash
# 1. Prerequisites
brew install terraform   # or apt install terraform

# 2. Configure secrets
cd deploy/terraform/single-server
cp .env.example .env
# Edit .env: set TF_VAR_hcloud_token, TF_VAR_tailscale_auth_key

# 3. Deploy
set -a && source .env && set +a
terraform init
terraform plan     # review what will be created
terraform apply    # provision server, firewall, DNS zone

# 4. Set nameservers at your domain registrar
terraform output nameservers
# → Set these as custom nameservers for tidemill.xyz at your registrar

# 5. Verify (wait ~2 min for cloud-init + DNS propagation)
curl https://tidemill.xyz/healthz

# 6. SSH if needed
ssh root@$(terraform output -raw server_ipv4)
```

### What cloud-init Does

The server bootstraps itself on first boot via [`cloud-init.yml`](https://github.com/ondraz/tidemill/tree/main/deploy/terraform/single-server/cloud-init.yml):

1. Updates packages and installs Docker
2. Clones the repo to `/opt/tidemill`
3. Generates a random Postgres password
4. Starts Docker Compose (all 5 services)
5. Enables unattended security updates
6. Reboots if the kernel was updated

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
| `kubernetes_secret` | Database credentials, Kafka config |
| `kubernetes_stateful_set` × 2 | PostgreSQL + Redpanda with Hetzner CSI volumes |
| `kubernetes_deployment` × 2 | API (2 replicas) + Worker (2 replicas) |
| `kubernetes_ingress_v1` | Traefik ingress with TLS |

### Architecture

```
                        Load Balancer (lb11)
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
          ┌─────────┐   ┌─────────┐   ┌─────────┐
          │  CP #1  │   │  CP #2  │   │  CP #3  │   Control Plane (cx22 × 3)
          │  k3s    │   │  k3s    │   │  k3s    │
          └─────────┘   └─────────┘   └─────────┘
               │              │              │
          ┌─────────┐   ┌─────────┐
          │Worker #1│   │Worker #2│   Worker Nodes (cx32 × N)
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
curl https://tidemill.xyz/healthz
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
| Volumes | 10 GB × 2 (PG + Redpanda) | 2 | ~€1 |
| **Total** | | | **~€33/mo** |

### Production Hardening

For a production Kubernetes deployment, consider:

- **Managed PostgreSQL** — replace the StatefulSet with Hetzner DBaaS or an external managed database. Remove the `kubernetes_stateful_set.postgres` resource and update `DATABASE_URL` in the secret.
- **Redpanda cluster** — replace the single-node StatefulSet with the [Redpanda Helm chart](https://github.com/redpanda-data/helm-charts) for a 3-broker cluster, or use Confluent Cloud / Amazon MSK.
- **Image registry** — push to GitHub Container Registry (`ghcr.io/ondraz/tidemill`) and pin image tags instead of `latest`.
- **Secrets management** — use [Sealed Secrets](https://github.com/bitnami-labs/sealed-secrets) or [External Secrets Operator](https://external-secrets.io/) instead of plain Kubernetes secrets.
- **Monitoring** — deploy Prometheus + Grafana via Helm for cluster and application metrics.
- **Backups** — use [Velero](https://velero.io/) for cluster backup, pg_dump CronJob for PostgreSQL.

## Compose ↔ Kubernetes Mapping

The Docker Compose and Kubernetes deployments use the same container images and environment variables. This table shows how each Compose concept translates:

| Docker Compose | Kubernetes | Notes |
|---------------|------------|-------|
| `postgres` service | `StatefulSet` + `PersistentVolumeClaim` | Hetzner CSI volumes |
| `redpanda` service | `StatefulSet` + `PersistentVolumeClaim` | Or Redpanda Helm chart |
| `api` service | `Deployment` + `Service` + `Ingress` | Scales horizontally |
| `worker` service | `Deployment` | Kafka rebalances partitions across replicas |
| `caddy` service | Traefik `Ingress` (built into kube-hetzner) | TLS via Let's Encrypt |
| `.env` file | `Secret` | |
| Docker `volumes` | `PersistentVolumeClaim` + Hetzner CSI | |
| `ports: 80, 443` | `LoadBalancer` service | Hetzner Cloud LB |

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
