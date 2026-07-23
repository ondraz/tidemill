---
title: Tidemill
description: This project — an open-source subscription analytics engine offering transparent, auditable metric computation for any billing system.
type: entity
tags: [project, analytics-tool, open-source]
updated: 2026-07-23
---

# Tidemill

> The subject of this wiki: open-source subscription analytics with auditable metric
> computation.

---

## What it is

An analytics engine that sits downstream of a billing system, computes SaaS metrics, and
shows its work. Revenue analytics come from [Stripe](stripe-billing.md) and
[Chargebee](chargebee.md); expense analytics from
[QuickBooks Online](quickbooks-online.md).

The one-line positioning: *your billing engine is open source, your database is open
source, your monitoring is open source — why are your subscription metrics computed by a
black box?*

## Key facts

| | |
|---|---|
| Category | Analytics layer |
| Licence | MIT, open source |
| Stack | Python 3.13+, PostgreSQL, Kafka/Redpanda, FastAPI, React frontend |
| Revenue sources | [Stripe](stripe-billing.md), [Chargebee](chargebee.md) — implemented |
| Expense sources | [QuickBooks Online](quickbooks-online.md) — implemented |
| Planned sources | [Lago](lago.md), [Kill Bill](kill-bill.md) — P1, same-database mode |
| Deployment | Docker Compose (single server) or k3s; self-hosted |

## Two integration modes

**Ingestion mode** — webhooks are translated to internal events, published to Kafka, and
materialised into analytics-owned PostgreSQL. This is the primary path and the reference
implementation. Used by Stripe and Chargebee.

**Same-database mode** — analytics queries the billing engine's own PostgreSQL directly.
Zero ETL, zero Kafka. Intended for Lago and Kill Bill, whose databases you already control.

See [overview](../../architecture/overview.md) and
[connectors](../../architecture/connectors.md).

## What it computes

[MRR](../concepts/mrr.md) and ARR, [churn](../concepts/churn.md),
[cohort retention](../concepts/cohort-retention.md) with
[NRR and GRR](../concepts/net-revenue-retention.md), [LTV](../concepts/ltv.md) and ARPU,
[trial conversion](../concepts/trial-conversion.md), usage revenue actuals, and expenses.
Every metric is a self-contained class with documented formula, SQL, assumptions and edge
cases — see [metrics](../../architecture/metrics.md) and
[definitions](../../definitions.md).

Metric SQL is built through [cubes and composable query fragments](../../architecture/cubes.md),
never string concatenation, and every subscription cube carries a `source` dimension so
metrics can be sliced by connector.

## Where it fits

Against the closed-source field — [ChartMogul](chartmogul.md),
[Baremetrics](baremetrics.md), [ProfitWell](profitwell.md), [SaaSGrid](saasgrid.md) —
Tidemill does not compete on feature count. It competes on
[metric transparency](../concepts/metric-transparency.md), self-hosting, and first-class
support for open-source billing engines.

## Explicit non-goals for V1

Payment processing, revenue recovery and dunning ([Baremetrics](baremetrics.md)
territory), board-ready financial reporting ([SaaSGrid](saasgrid.md) territory), built-in
CRM ([ChartMogul](chartmogul.md) territory), and general-purpose BI.

## Related

- [Product positioning](../../research/product-positioning.md) — the full argument
- [Competitive matrix](../../research/competitive-matrix.md) — feature comparison
- [Metric Transparency](../concepts/metric-transparency.md) — the core thesis

## Sources

- [Architecture overview](../../architecture/overview.md)
- [Metric definitions](../../definitions.md)
- `AGENTS.md` — project conventions and current state
