---
title: Trial Conversion
description: The share of trials that become paying customers — a leading indicator, and a metric whose historical values legitimately change after the fact.
type: concept
tags: [metric, funnel, implemented]
updated: 2026-07-23
---

# Trial Conversion

> The clearest leading indicator in a subscription business — and the one metric where
> last quarter's number is expected to move.

---

## The idea

Trials run 7–14 days typically, 30 for enterprise. The conversion rate is the fraction of
started trials that become paid subscriptions. Freemium conversion, a related but distinct
motion, typically runs 2–5%.

Trial conversion leads [MRR](mrr.md) by roughly one billing cycle, which makes it the
earliest reliable signal that acquisition quality or onboarding has shifted — well before
it shows up in revenue.

## The retroactive cohort problem

A trial started in January that converts in March: which period does it count in?

Tidemill uses the **retroactive cohort model**, matching
[ChartMogul](../entities/chartmogul.md). The trial is fixed to the period of its
`trial_started` event and its eventual outcome rolls back to that cohort no matter when it
lands. A March conversion updates January's rate.

The alternative — counting conversions in the period they occur — keeps history immutable
but produces a number that is not a conversion *rate* of anything coherent, mixing
numerator and denominator from different populations.

The trade-off is real and worth stating plainly: **recent periods are provisional.** Trials
that are neither converted nor expired are still pending, so the most recent months will
move as they resolve. A dashboard reader who does not know this will misread a dip.

## How Tidemill computes it

Conversions over trials started, both scoped to the cohort period by `started_at`, with
conversion counted at any later time.

**Authoritative formulas:** [definitions.md — Trial Conversion Rate](../../definitions.md).
**Implementation:** `tidemill/metrics/trials/`.

!!! warning "Known documentation drift"
    `definitions.md` files Trial Conversion under "Planned (P1) — designed but not yet
    implemented", but `tidemill/metrics/trials/` ships and is registered. The formulas are
    current; the status label is stale. Recorded in the [wiki log](../log.md) on 2026-07-23.

## Contested ground

- **Do trials count as active subscriptions?** They affect customer counts, ARPU, and
  therefore [LTV](ltv.md) if included. Tidemill tracks trials as their own funnel.
- **Expired vs. cancelled trials.** A trial abandoned on day two and one that ran its full
  length are both non-conversions, but they mean different things about the product.
- **Provisional recent periods.** Shared with ChartMogul, and a frequent source of
  "why did last month's number change?" confusion.

## Related

- [MRR](mrr.md) — what conversion feeds
- [Churn](churn.md) — the other end of the lifecycle
- [Baremetrics](../entities/baremetrics.md) — Trial Insights as a product feature
- [Cohort Retention](cohort-retention.md) — same cohort logic, different event

## Sources

- [definitions.md](../../definitions.md) — formula and ChartMogul alignment
- [Market overview](../../research/market-overview.md) — trial lengths, freemium conversion rates
