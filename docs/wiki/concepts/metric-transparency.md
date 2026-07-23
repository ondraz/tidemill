---
title: Metric Transparency
description: The thesis that subscription metrics should be auditable — the single idea Tidemill's positioning rests on.
type: concept
tags: [thesis, positioning, differentiation]
updated: 2026-07-23
---

# Metric Transparency

> There is no industry standard for calculating MRR, churn, or LTV. Every tool decides,
> and every closed-source tool hides the decision.

---

## The idea

Reasonable, competent people disagree on questions that materially change the numbers:

- Should annual subscriptions be spread monthly or recognised at payment time?
- How are mid-cycle upgrades attributed?
- When does a churned customer stop affecting cohort metrics?
- Do free trials count as active subscriptions?
- Does smoothed [usage revenue](usage-based-pricing.md) belong in MRR?

None has a correct answer. Every analytics tool answers all of them, and the answers
compound — [MRR](mrr.md) feeds [churn](churn.md) feeds
[NRR](net-revenue-retention.md) feeds [LTV](ltv.md).

The failure mode this produces is specific and common: your computed MRR does not match
the CFO's spreadsheet, and with a closed-source tool there is no way to find out which
assumption differs. Users of [ProfitWell](../entities/profitwell.md) report exactly this —
metrics diverging from their own calculations with no route to an explanation.

## Why it is the differentiator

Tidemill cannot differentiate on price. ProfitWell is free, and
[ChartMogul](../entities/chartmogul.md) has a free tier — free tiers have compressed
pricing power across the whole category. Nor can a young open-source project win on
feature count against [Baremetrics](../entities/baremetrics.md) or
[SaaSGrid](../entities/saasgrid.md)'s 150+ metrics.

What none of them offers is auditability. Every tool in the category is closed source, so
transparency is the one axis where the competitive field is empty rather than crowded.
See [analytics tools](../../research/analytics-tools.md) and
[product positioning](../../research/product-positioning.md).

The argument is sharpest for users whose billing is already unusual —
[usage-based and hybrid](usage-based-pricing.md) pricing, or heavily customised
[Kill Bill](../entities/kill-bill.md) deployments — because generic formulas are least
likely to match their reality and most likely to be wrong in ways only they can detect.

## What it means in practice

Transparency is a set of enforced commitments, not a slogan:

1. **Every metric documents formula, SQL, assumptions, and edge cases** — a stated
   convention in `AGENTS.md`, applied per metric in
   [metrics](../../architecture/metrics.md).
2. **Divergences from the category norm are tabulated, not buried.**
   [definitions.md](../../definitions.md) carries an explicit *Differences from ChartMogul*
   section covering same-period joiners, gross vs. net revenue churn, reactivation in Quick
   Ratio, LTV lookback, and churn recognition timing.
3. **Metric SQL is composed, not concatenated** — built through
   [cubes and query fragments](../../architecture/cubes.md) so the executed query is
   inspectable rather than assembled from strings.
4. **Approximations are labelled.** Trailing-3-month usage smoothing, no mid-period
   extrapolation, provisional [trial conversion](trial-conversion.md) periods — each is
   stated where it applies.

The test of the thesis is simple: a user migrating from another tool should be able to
find the source of any discrepancy in the documentation, without reading the code. Reading
the code is the fallback guarantee, not the intended path.

## Contested ground

Transparency is not free. Publishing every divergence invites "why is your churn higher
than ChartMogul's?" from users who would otherwise never have asked. The bet is that a
question you can answer is worth more than a discrepancy you cannot.

## Related

- [Tidemill](../entities/tidemill.md) — how the thesis shapes the product
- [MRR](mrr.md), [Churn](churn.md), [LTV](ltv.md) — where divergences concentrate
- [Usage-Based Pricing](usage-based-pricing.md) — the sharpest case
- [ProfitWell](../entities/profitwell.md) — the opaque-free counterexample

## Sources

- [Product positioning](../../research/product-positioning.md) — the full argument
- [definitions.md](../../definitions.md) — divergences in practice
- [Analytics tools](../../research/analytics-tools.md) — no open-source option exists
