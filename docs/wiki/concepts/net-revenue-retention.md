---
title: Net Revenue Retention (NRR & GRR)
description: Whether revenue from the existing customer base grows or shrinks on its own — the headline efficiency metric for SaaS, and its gross counterpart.
type: concept
tags: [metric, retention, implemented]
updated: 2026-07-23
---

# Net Revenue Retention (NRR & GRR)

> Does your existing customer base grow revenue without any new customers?

---

## The idea

**NRR** takes MRR at period start, adds expansion and reactivation, subtracts contraction
and churn, and divides by the starting figure. Above 100% means expansion outpaces losses —
"net negative churn", where the business grows even if it acquires no one.

**GRR** runs the same calculation with expansion removed. It measures pure preservation and
is therefore always ≤ 100%.

Read together they separate two different competencies. High GRR means the product retains.
High NRR with mediocre GRR means the business is leaky but sells well into the accounts
that stay. Only one of those survives a downturn.

NRR > 100% is the widely cited benchmark for healthy SaaS.

## Why it matters

NRR is the metric investors anchor on, because it isolates the compounding part of a
subscription business from the acquisition engine. It is also the most sensitive to
definitional choices: it depends on the classification of *every* MRR movement, so any
disagreement about what counts as expansion versus new — or about
[usage revenue](usage-based-pricing.md) — lands here amplified.

## How Tidemill computes it

Both are derived from the same MRR movement ledger as [MRR](mrr.md) and
[churn](churn.md), so they cannot disagree with the waterfall by construction. That
shared-ledger property is the reason all three metrics reconcile.

**Authoritative formulas:** [definitions.md — Retention](../../definitions.md).
**Implementation:** `tidemill/metrics/retention/`.

## Contested ground

- **Usage-driven movement.** Because Tidemill's usage MRR is a trailing 3-month average, a
  customer's usage drift emits expansion or contraction movements that flow into NRR. Tools
  excluding usage from MRR entirely report a different NRR for identical underlying revenue.
- **Cohort-level revenue retention.** ChartMogul offers Net MRR Retention *per cohort*;
  Tidemill currently exposes NRR and GRR globally and tracks
  [cohort retention](cohort-retention.md) by customer count only. This is a known gap.
- **Reactivation.** Tidemill counts reactivation in the numerator. Treatment varies across
  tools — the same divergence appears in Quick Ratio.

## Related

- [MRR](mrr.md) — the movement ledger both metrics read
- [Churn](churn.md) — the loss side
- [Cohort Retention](cohort-retention.md) — the customer-count view
- [ChartMogul](../entities/chartmogul.md) — cohort revenue retention comparison

## Sources

- [definitions.md](../../definitions.md) — NRR and GRR formulas
- [Market overview](../../research/market-overview.md) — benchmark ranges
