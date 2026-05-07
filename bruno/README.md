# Tidemill API — Bruno Collection

A runnable, file-based API explorer for the Tidemill REST API. Use it to
discover what's possible without trawling routes.

## Getting started

1. Install Bruno (https://www.usebruno.com/) — desktop app or `bru` CLI.
2. Open this folder (`bruno/`) as a collection.
3. Pick the **Local** environment (top-right). Defaults to
   `http://localhost:8000`. Leave `apiKey` empty when running with auth
   disabled (the default in dev compose); set it to a `tk_…` API key when
   `TIDEMILL_AUTH_ENABLED=true`.
4. Click any request → **Send**.

CLI alternative:

```bash
npm i -g @usebruno/cli
cd bruno
bru run --env Local "Metrics - MRR/01_current.bru"
bru run --env Local "Metrics - MRR"        # whole folder
```

## How the collection is organised

| Folder | What it shows |
| --- | --- |
| `Health/` | Liveness + readiness probes (no auth). |
| `Auth/` | `/auth/me`, `/auth/config`, API key CRUD (Clerk-only). |
| `Sources/` | Connector source registry + manual backfill trigger. |
| `Webhooks/` | Stripe and generic webhook receivers. |
| `Metrics - Discovery/` | List metrics, get the global KPI summary, introspect a metric's filterable dimensions, run a metric via `POST` body. |
| `Metrics - MRR/` | Current snapshot, time series, breakdown, waterfall, ARR, components (subscription vs usage) — plus advanced examples for filters, dimensions, segments, and compare-mode. |
| `Metrics - Churn/` | Logo churn, revenue churn, churned-customer detail, churn revenue events. |
| `Metrics - Retention/` | Cohort matrix, NRR, GRR. |
| `Metrics - LTV/` | Simple LTV, ARPU, cohort LTV. |
| `Metrics - Trials/` | Conversion rate, trial series, conversion funnel. |
| `Metrics - Usage Revenue/` | Finalized monthly metered charges as actuals — total, time series, per customer. Sibling to MRR's smoothed trailing-3m usage component. |
| `Segments/` | Segment DSL — list/create/get/update/delete, plus the `/validate` linter. |
| `Attributes/` | Attribute definitions, distinct values, customer attribute writes, CSV import. |
| `Dashboards/` | Dashboard + section CRUD and chart placement. |
| `Charts/` | Saved chart CRUD (the "library" attached into dashboards). |

## Auth model

- **No auth (local default):** leave `apiKey` blank. All `/api/*`
  endpoints accept requests as user `anonymous`.
- **API key:** set `apiKey` to a `tk_…` token from `POST /api/keys`. The
  collection sends it as `Authorization: Bearer {{apiKey}}`.
- **API key management** (`Auth/03_*` – `Auth/05_*`) deliberately rejects
  `Bearer tk_…` and requires a real Clerk JWT — paste a fresh JWT into
  `apiKey` for those three requests.

## Cross-cutting query params worth knowing

These are accepted by every metric GET endpoint via the shared
`parse_spec` dependency (`tidemill/metrics/route_helpers.py`):

| Param | Meaning | Example |
| --- | --- | --- |
| `dimensions` | Group by one or more cube dimensions (repeatable) | `dimensions=customer_country&dimensions=plan_name` |
| `filter` | `key=value` filter on a cube dim/attr (repeatable) | `filter=currency=USD` |
| `granularity` | Override the time-series bucket | `granularity=week` |
| `segment` | Saved segment id to filter by | `segment={{segmentId}}` |
| `compare_segments` | Saved segment ids to compare side-by-side | `compare_segments=…&compare_segments=…` |

The `Metrics - MRR/` folder has individual requests demonstrating each.

## Discovering the rest

- `GET /docs` — the FastAPI Swagger UI is the live source of truth for
  every parameter shape.
- `GET /api/metrics` — list of registered metrics.
- `GET /api/metrics/{metric}/fields` — every dimension and attribute the
  segment builder can reference, with inferred types.
