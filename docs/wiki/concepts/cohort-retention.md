---
title: Cohort Retention
description: What fraction of customers who started together are still active N months later — the clearest signal of whether a product actually retains.
type: concept
tags: [metric, retention, implemented]
updated: 2026-07-23
---

# Cohort Retention

> Group customers by when they arrived, then watch each group decay.

---

## The idea

A customer's cohort is the month of their first subscription. Retention is the fraction of
that cohort still active in each subsequent month.

The reason to bother with cohorts rather than an aggregate churn rate: aggregates hide
whether things are getting better. A company acquiring rapidly can post a flat overall
churn rate while every successive cohort retains worse than the last — growth masks decay
because new customers have not had time to leave yet. Cohort curves expose that
immediately; a single churn number never will.

Cohort assignment is **immutable** in Tidemill: set on first subscription and never
changed, even across churn and reactivation. Without that rule, cohorts would reshuffle
retroactively and historical curves would not be comparable.

## Why it matters

Cohort analysis is the main axis of analytical depth in this category and the clearest
place where tools differentiate. [ChartMogul](../entities/chartmogul.md) leads on it with
custom dimensions; [Baremetrics](../entities/baremetrics.md) and
[ProfitWell](../entities/profitwell.md) offer basic monthly cohorts.

It also matters disproportionately in high-churn segments — physical subscription boxes
run 10–12% monthly churn, where the shape of the decay curve is the entire business
question.

## How Tidemill computes it

Retention is customers-from-cohort-active-in-month over cohort size. A customer counts as
active in a month if they had at least one active subscription during it.

Cohorts compose with [segmentation](../../architecture/segments.md), so retention can be
sliced by any customer attribute — plan, geography, acquisition channel, or the
[billing source](../entities/chargebee.md) itself.

**Authoritative formulas:** [definitions.md — Cohort Retention](../../definitions.md).
**Implementation:** `tidemill/metrics/retention/`.

## Contested ground

- **Customer vs. revenue cohorts.** Tidemill tracks customer retention per cohort;
  revenue retention exists only globally as [NRR/GRR](net-revenue-retention.md).
  ChartMogul offers Net MRR Retention per cohort. This is an acknowledged gap.
- **"Active" in a partial month.** Tidemill counts any active subscription during the
  month. Alternatives — active on the last day, active for the full month — produce
  visibly different curves for mid-month churners.
- **Reactivation.** Because cohort membership is immutable, a reactivated customer
  reappears in their original cohort, which can make a curve tick *upward*. That is
  intentional and worth knowing before reading a chart.

## Related

- [Churn](churn.md) — the aggregate view cohorts decompose
- [Net Revenue Retention](net-revenue-retention.md) — the revenue-side counterpart
- [LTV](ltv.md) — cohort LTV uses the same grouping
- [ChartMogul](../entities/chartmogul.md) — the depth benchmark

## Sources

- [definitions.md](../../definitions.md) — retention formulas and cohort conventions
- [segments](../../architecture/segments.md) — segmentation model
