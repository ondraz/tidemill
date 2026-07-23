---
title: Churn
description: Customers or revenue lost in a period — logo churn and revenue churn — and the definitional choices that make the number contestable.
type: concept
tags: [metric, retention, implemented]
updated: 2026-07-23
---

# Churn

> The fraction of customers (logo churn) or revenue (revenue churn) lost in a period.
> Simple to state, unusually easy to compute three different ways.

---

## The idea

Churn splits into two families:

**Logo churn** counts customers. A customer churns when their last active subscription
ends — active subscription count reaching zero, not merely one subscription among several
being cancelled.

**Revenue churn** counts MRR lost. A customer downgrading from $500 to $50 is not a logo
churn at all, but is a substantial revenue event.

The two diverge sharply by segment mix: losing many small customers and losing one large
one look identical in logo churn and nothing alike in revenue churn.

## Voluntary vs. involuntary

Involuntary churn — failed payments rather than a decision to leave — accounts for
20–40% of total subscription churn, and smart retry logic recovers 60–80% of failed
charges. [Stripe](../entities/stripe-billing.md) reports ~41% of failed invoices recovered
via ML retries.

This distinction is the entire premise of
[Baremetrics Recover](../entities/baremetrics.md) and ProfitWell Retain. Tidemill treats
dunning as an [explicit non-goal](../entities/tidemill.md) — billing-engine territory —
but the *analytical* distinction between voluntary and involuntary churn remains
meaningful and is not currently broken out.

## How Tidemill computes it

The scoping rule does the real work: only customers active at period start
($C_{\text{start}}$) can appear in the numerator. Customers who both join and churn inside
the same period are excluded — otherwise a burst of trial signups would manufacture
churn out of nothing.

Revenue churn is **gross**: churn MRR only, excluding contraction and expansion, since
those are visible separately in the [MRR](mrr.md) waterfall.

Pure-usage customers churn too. A metered-only customer has zero subscription MRR but
accrues usage MRR once their first usage invoice is paid; on cancellation the churn amount
is `subscription_mrr + usage_mrr`, so neither component is lost.

**Authoritative formulas:** [definitions.md — Churn](../../definitions.md).
**Implementation:** `tidemill/metrics/churn/`.

## Contested ground

Churn is the metric where Tidemill most visibly diverges from
[ChartMogul](../entities/chartmogul.md), and each divergence is documented rather than
buried:

| Question | Tidemill | ChartMogul |
|---|---|---|
| Churn-then-reactivate in one period | Counts as churn | Netted out |
| Revenue churn definition | Gross churn only | Gross (incl. contraction) *and* net variants |
| Recognition timing | At status change / period end | Configurable across three options |
| Incomplete periods | Actuals only | Extrapolated to full-period rate |

None of these has a correct answer. The point is that a user reconciling Tidemill against
a previous tool can find the difference in a table instead of guessing — see
[metric transparency](metric-transparency.md).

## Related

- [MRR](mrr.md) — the denominator
- [Cohort Retention](cohort-retention.md), [Net Revenue Retention](net-revenue-retention.md)
- [LTV](ltv.md) — churn rate is its denominator
- [Baremetrics](../entities/baremetrics.md) — the action layer on involuntary churn

## Sources

- [definitions.md](../../definitions.md) — formulas and ChartMogul divergences
- [Market overview](../../research/market-overview.md) — involuntary churn and dunning statistics
