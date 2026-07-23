---
title: LTV — Customer Lifetime Value
description: Expected total revenue from a customer before they churn; the most assumption-laden metric in the category and the foundation of unit economics.
type: concept
tags: [metric, unit-economics, implemented]
updated: 2026-07-23
---

# LTV — Customer Lifetime Value

> ARPU divided by churn rate. Two inputs, and an unusually large amount of room to
> disagree about both.

---

## The idea

If customers pay ARPU per month and a fraction $c$ of them leave each month, the average
customer stays $1/c$ months and is worth $\text{ARPU}/c$. That is the whole model.

Its fragility follows directly: LTV is a ratio of two estimates, one in the denominator.
At low churn rates small absolute changes swing LTV enormously — 1% monthly churn implies
a 100-month lifetime, 2% implies 50. The metric is least stable exactly where the business
is healthiest.

**Cohort LTV** sidesteps the model entirely by measuring actual cumulative revenue per
customer within a cohort. Slower to mature, but it is an observation rather than a
projection.

## Why it matters

LTV is only meaningful against CAC. The LTV:CAC ratio — with > 3x the conventional
healthy benchmark — is the standard test of whether growth spend is sustainable.

Tidemill computes LTV today but **not CAC**, which remains
[P1 and unimplemented](../entities/tidemill.md). CAC requires acquisition spend, which is
why [expense analytics](../../architecture/expenses.md) via
[QuickBooks Online](../entities/quickbooks-online.md) is a prerequisite rather than a
side quest.

## How Tidemill computes it

LTV is ARPU over [logo churn rate](churn.md), where ARPU is [MRR](mrr.md) over active
customer count. Cohort LTV sums all paid invoices per customer in base currency, divided
by cohort size.

**Authoritative formulas:** [definitions.md — LTV](../../definitions.md).
**Implementation:** `tidemill/metrics/ltv/`.

!!! warning "Known documentation drift"
    `definitions.md` files LTV under "Planned (P1) — designed but not yet implemented",
    but `tidemill/metrics/ltv/` ships and is registered. The formulas there are current;
    the status label is stale. Recorded in the [wiki log](../log.md) on 2026-07-23.

## Contested ground

- **Churn denominator window.** Tidemill uses the current-period churn rate.
  [ChartMogul](../entities/chartmogul.md) uses a 6-month trailing average to damp the
  volatility described above. ChartMogul's is arguably the better estimator; Tidemill's
  is the more legible one, since "which six months?" has no visible answer. A configurable
  lookback is a candidate improvement.
- **Revenue vs. margin.** LTV computed on revenue ignores cost of service. For
  usage-heavy products with real COGS this overstates value materially.
- **Logo vs. revenue churn as denominator.** Using logo churn implicitly assumes a
  departing customer was average-sized.

## Related

- [Churn](churn.md) — the denominator
- [MRR](mrr.md) — via ARPU
- [Cohort Retention](cohort-retention.md) — cohort LTV shares its grouping
- [QuickBooks Online](../entities/quickbooks-online.md) — the path to CAC

## Sources

- [definitions.md](../../definitions.md) — LTV, ARPU, and cohort LTV formulas
- [Market overview](../../research/market-overview.md) — LTV:CAC benchmarks
