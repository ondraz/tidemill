---
title: Usage-Based Pricing
description: Charging for consumption rather than access — the dominant emerging pricing pattern and the single biggest source of analytics complexity.
type: concept
tags: [pricing, market-trend, revenue]
updated: 2026-07-23
---

# Usage-Based Pricing

> Roughly 85% of software vendors have adopted some form of usage-based pricing.
> It is also the reason subscription metrics stopped being straightforward.

---

## The idea

Instead of paying for access, customers pay for consumption — API calls, tokens, GB,
compute-seconds. **Hybrid** models combine a committed base fee with usage overages, and
are the dominant shape in AI and cloud products.

The analytics problem is definitional, not technical. "Recurring revenue" assumes a
predictable amount recurring on a schedule. Usage revenue is neither predictable nor
committed, yet it is unquestionably real revenue that recurs. Every subscription analytics
tool has to decide what to do with it, and the decision is a convention rather than a fact.

## Why it matters

This is the strongest structural argument for Tidemill's existence. Generic metric formulas
were designed for flat-rate subscriptions; a business billing on API calls plus a base
subscription plus prepaid credits across multiple currencies has metrics that no
one-size-fits-all calculation reproduces correctly.

That gap is where closed-source tools fail their users most visibly: when the number is
wrong, there is no way to find out why. See
[metric transparency](metric-transparency.md) and
[product positioning](../../research/product-positioning.md).

## How the billing layer shapes what is possible

The upstream engine determines what analytics can even see:

| Engine | Usage metering | Consequence for analytics |
|---|---|---|
| [Stripe Billing](../entities/stripe-billing.md) | Pre-aggregated only | Raw meter events unavailable; must work from invoice line items |
| [Lago](../entities/lago.md) | Event-based, ~15k events/sec | Granular usage events available directly from the database |
| [Kill Bill](../entities/kill-bill.md) | Plugin-based | Depends entirely on the deployed plugin |

Stripe's pre-aggregation constraint is precisely why Tidemill derives usage MRR from
finalized invoice line items rather than a metering stream.

## How Tidemill handles it

Two distinct numbers, deliberately kept separate:

**Usage MRR** — a trailing 3-month average feeding [MRR](mrr.md). Smoothed, so bursty
consumption does not whipsaw churn and LTV calculations.

**Usage revenue** — raw monthly usage charges as actuals, no smoothing. For auditing meter
events, reconciling against invoices, and answering "what did customers actually pay for
usage last month".

Both read the same underlying table, so they can differ in presentation but never in
underlying data. Implementation: `tidemill/metrics/usage_revenue/`.

Pure-usage customers are first-class: zero subscription MRR, positive usage MRR after
their first paid usage invoice, and both components counted on
[churn](churn.md).

## Contested ground

- **Should usage count as MRR at all?** It is not committed revenue. Tidemill includes a
  smoothed version and says so explicitly rather than burying the choice.
- **How much smoothing?** Trailing 3 months is convention, not derivation. The trade-off
  is a ~1.5-month lag against volatility; "most recent invoice" is more current but too
  noisy to drive churn or LTV.
- **Prepaid credits and wallets** ([Lago](../entities/lago.md) supports these) have no
  settled treatment in MRR at all.

## Related

- [MRR](mrr.md) — where smoothed usage lands
- [Churn](churn.md) — pure-usage customer handling
- [Lago](../entities/lago.md), [Stripe Billing](../entities/stripe-billing.md)
- [Metric Transparency](metric-transparency.md)

## Sources

- [Market overview](../../research/market-overview.md) — adoption statistics, pricing model table
- [Billing engines](../../research/billing-engines.md) — metering architecture comparison
- [definitions.md](../../definitions.md) — usage MRR and usage revenue formulas
- [Orb — Subscription vs. Usage-Based Revenue](https://www.withorb.com/blog/usage-based-revenue-vs-subscription-revenue)
