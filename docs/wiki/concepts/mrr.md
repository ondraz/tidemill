---
title: MRR — Monthly Recurring Revenue
description: Normalized monthly revenue from active subscriptions; the core health metric and the base every other subscription metric is derived from.
type: concept
tags: [metric, revenue, implemented]
updated: 2026-07-23
---

# MRR — Monthly Recurring Revenue

> Normalized monthly revenue from all active subscriptions. The number everything else
> is built on.

---

## The idea

MRR converts subscriptions billed on different cycles into a comparable monthly figure —
an annual plan contributes one twelfth per month, a weekly plan contributes 52/12. What
makes it interesting is not the arithmetic but the boundary decisions: what counts as
active, when a change is recognised, and how non-committed revenue is treated.

Those decisions are where tools disagree, and why
[metric transparency](metric-transparency.md) matters more here than anywhere else.

## Why it matters

MRR is the base of the dependency chain. [Churn](churn.md) is measured against MRR at
period start, [NRR and GRR](net-revenue-retention.md) are ratios over it, and
[LTV](ltv.md) derives from ARPU which derives from MRR. An idiosyncratic MRR definition
propagates into every downstream number.

ARR is simply MRR × 12. ([ChartMogul](../entities/chartmogul.md) calls the same quantity
*Annual Run Rate*; Tidemill uses the more common *Annual Recurring Revenue*.)

## How Tidemill computes it

Tidemill splits MRR into two components:

**Subscription MRR** — committed recurring revenue from licensed items, normalized to a
monthly interval and computed at subscription-event time.

**Usage MRR** — a **trailing 3-month average** of finalized usage charges, matching
[ChartMogul](../entities/chartmogul.md) and [Baremetrics](../entities/baremetrics.md)
convention. Smoothing keeps bursty workloads from whipsawing the number; the cost is a
~1.5-month lag. Customers with under three months of history average over what exists,
so a first-month customer with $40 of usage carries $40, not $13.33.

The smoothed usage component is deliberately *not* the same thing as
[usage revenue actuals](usage-based-pricing.md), which report raw monthly charges
unsmoothed. Both are backed by the same table, so they cannot drift apart.

Every subscription change produces exactly one **movement** — new, expansion, contraction,
churn, or reactivation — and the MRR waterfall chains these month over month.

**Authoritative formulas:** [definitions.md — MRR](../../definitions.md).
**Implementation:** `tidemill/metrics/mrr/`, documented in
[metrics](../../architecture/metrics.md).

## Contested ground

- **Annual plans** — spread monthly (Tidemill and the category standard) or recognised at
  payment time? Spreading is near-universal in subscription analytics but disagrees with
  cash accounting, which is a common source of CFO-vs-dashboard arguments.
- **Usage revenue** — whether it belongs in MRR at all. It is not *committed*, so counting
  a smoothed average as "recurring" is a convention, not a fact. Tidemill states the
  convention explicitly and exposes actuals separately.
- **Mid-period extrapolation** — ChartMogul projects incomplete periods to a full-period
  rate; Tidemill shows actuals only.

## Related

- [Churn](churn.md), [Net Revenue Retention](net-revenue-retention.md), [LTV](ltv.md)
- [Usage-Based Pricing](usage-based-pricing.md) — the usage component's source
- [Metric Transparency](metric-transparency.md)
- [Stripe Billing](../entities/stripe-billing.md) — why usage is smoothed rather than metered

## Sources

- [definitions.md](../../definitions.md) — canonical formulas and ChartMogul divergences
- [metrics](../../architecture/metrics.md) — implementation and SQL
