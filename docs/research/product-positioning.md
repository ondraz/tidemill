# Product Positioning: Open-Source Subscription Analytics

> Defining where an open-source subscription analytics package fits in the ecosystem and why it should exist.
> Last updated: March 2026

---

## The Two-Layer Stack

The subscription infrastructure stack has two distinct layers:

```
┌─────────────────────────────────────────────────────┐
│                  ANALYTICS LAYER                     │
│  Reads billing data → computes metrics → visualizes  │
│                                                       │
│  Closed-source:  ChartMogul, Baremetrics,            │
│                  ProfitWell, SaaSGrid                 │
│                                                       │
│  Open-source:    [ THIS PROJECT ]                    │
└──────────────────────┬──────────────────────────────┘
                       │ reads from
┌──────────────────────┴──────────────────────────────┐
│                  BILLING LAYER                       │
│  Processes subscriptions → invoices → payments       │
│                                                       │
│  Closed-source:  Stripe Billing, Chargebee,          │
│                  Recurly, Zuora, Maxio                │
│                                                       │
│  Open-source:    Lago, Kill Bill                     │
└─────────────────────────────────────────────────────┘
```

The billing layer has credible open-source options (Lago, Kill Bill). The analytics layer does not. This project fills that gap.

---

## Positioning Statement

For **subscription businesses and open-source billing users** who need to **understand their recurring revenue metrics**, this project is an **open-source subscription analytics engine** that provides **transparent, auditable, and customizable metric computation**.

Unlike ChartMogul, Baremetrics, or ProfitWell, this project gives you full visibility into how every metric is calculated, lets you self-host your analytics alongside your billing data, and provides first-class integration with open-source billing engines like Lago and Kill Bill — not just Stripe.

---

## Why Open-Source Analytics Matters

### 1. Metric Definitions Are Not Standardized

There is no industry standard for how to calculate MRR, churn, or LTV. Reasonable people disagree on questions like: should annual subscriptions be spread monthly or counted at payment time? How do you handle mid-cycle upgrades? When does a churned customer stop affecting your cohort metrics? Do free trials count as active subscriptions?

Every closed-source analytics tool makes these decisions for you and hides the implementation. When your computed MRR doesn't match your CFO's spreadsheet, you have no way to understand why. Open-source means you can read the code that computes every number.

### 2. Billing Complexity Demands Customization

The shift toward usage-based and hybrid pricing models (85% of software vendors by 2026) creates billing complexity that generic formulas cannot handle. A company billing on API calls + base subscription + prepaid credits + multi-currency needs analytics that understand their specific billing model. Closed-source tools offer one-size-fits-all calculations. Open-source allows metric computation to be configured or extended for any billing model.

### 3. Data Ownership and Residency

Companies in regulated industries (healthcare, fintech, government) often cannot send billing data to third-party SaaS analytics tools. Self-hosted analytics paired with self-hosted billing (Lago, Kill Bill) creates a complete subscription stack where all data stays on the company's infrastructure.

### 4. The Open-Source Billing Ecosystem Needs It

Lago has 7K+ GitHub stars and growing adoption. Kill Bill has been production-ready for a decade. Both have vibrant communities. But neither has a dedicated open-source analytics companion. Users of these tools currently must either build custom dashboards from scratch, use generic BI tools (Metabase, Grafana) with manual metric definitions, or export data into closed-source analytics tools designed primarily for Stripe. This is a gap the community actively feels.

---

## Competitive Differentiation

### vs. ChartMogul
ChartMogul is the analytics depth leader with strong segmentation and cohort analysis. It is the closest competitor in terms of analytical ambition. The differentiation is not feature count but philosophy: transparent metric computation, self-hosting, and native open-source billing support. ChartMogul is also increasingly expensive at scale ($100/mo per $10K MRR).

### vs. Baremetrics
Baremetrics differentiates on action — revenue recovery, forecasting, cancellation insights. An open-source analytics tool should not compete on these features initially. The differentiation is transparency and customizability of the core metric layer. Baremetrics is also the most expensive option with no free tier.

### vs. ProfitWell (Paddle)
ProfitWell is free, making it the hardest competitor to undercut on price. But free comes with strings: ProfitWell is a Paddle acquisition play, metric calculations are opaque, and innovation has stalled. The differentiation is that open-source free is structurally different from VC-subsidized free — it doesn't come with strategic incentives to move you to a specific billing platform.

### vs. SaaSGrid
SaaSGrid targets CFOs and finance teams with 150+ metrics and accounting integration. This is a different buyer entirely. An open-source tool initially targets engineering and product teams who want programmatic access to metric computation, not board-ready financial reporting.

### vs. Building It Yourself
The most common current approach for open-source billing users is building custom dashboards. This works for basic metrics but breaks down for cohort analysis, segmentation, and complex metric computation. An open-source analytics package provides the rigor of a dedicated tool with the flexibility of building your own.

---

## Target Users (in Priority Order)

### Primary: Open-Source Billing Users
Companies using Lago or Kill Bill who have no dedicated analytics option today. They are already philosophically aligned with open-source infrastructure and actively need this tool. This is the beachhead market.

### Secondary: Self-Hosting Mandate
Companies that cannot or will not send billing data to third-party SaaS. Regulated industries, government contractors, privacy-conscious startups. They may be using Stripe for billing but need analytics that stays on their infrastructure.

### Tertiary: Metric Customizers
Companies with complex billing models (usage-based, hybrid, multi-product) whose metrics in existing tools don't match their internal definitions. They need the ability to customize how metrics are computed. These users are often currently building custom SQL dashboards.

### Long-Tail: Cost-Conscious Startups
Early-stage companies for whom even ChartMogul's free tier is limiting, or who want to avoid vendor lock-in from the start. ProfitWell is the main competitor here, but data ownership and transparency are meaningful differentiators for technical founders.

---

## What to Build First (Suggested MVP Scope)

Based on the competitive analysis, the MVP should focus on the core metric engine — the part that is most differentiated and hardest to replicate:

**Must-Have (P0)**
- MRR computation with transparent, documented calculation logic
- Churn calculation (logo churn, revenue churn, net revenue churn) with configurable definitions
- Basic cohort analysis (monthly retention cohorts)
- Stripe integration (largest potential user base)
- Lago integration (strongest community alignment)
- CLI and/or API for programmatic access to metrics
- Self-hosted deployment (Docker)

**Nice-to-Have (P1)**
- LTV and CAC computation
- Expansion and contraction MRR breakdown
- Customer segmentation by plan, geography, or custom attributes
- Kill Bill integration
- Web dashboard UI
- Data warehouse export (PostgreSQL, CSV)

**Future Considerations (P2)**
- Forecasting
- Revenue recovery / dunning (likely out of scope — billing engine territory)
- Benchmarking
- CRM integration
- Revenue recognition

**Explicit Non-Goals for V1**
- Payment processing (this is a billing engine concern, not analytics)
- Revenue recovery / dunning automation (Baremetrics territory — complex, different competency)
- Board-ready financial reporting (SaaSGrid territory — different buyer)
- Built-in CRM (ChartMogul territory — scope creep risk)

---

## Success Metrics for the Project

As an open-source project, success metrics differ from SaaS:

**Adoption indicators:** GitHub stars, forks, Docker pulls, npm/pip installs.
**Community health:** open issues, PRs from external contributors, Discord/community activity.
**Integration breadth:** number of billing sources supported, number of deployment environments tested.
**Accuracy validation:** documented comparisons showing metric output matches expected calculations for known billing scenarios.

A reasonable 6-month goal would be: 1,000+ GitHub stars, 3+ billing engine integrations (Stripe, Lago, Kill Bill), documented metric calculation methodology that becomes a reference in the community, and at least 5 production deployments from community members.

---

## The Narrative for the Community

The pitch to the open-source community is straightforward:

> Your billing engine is open-source. Your database is open-source. Your monitoring is open-source. Why are your subscription metrics computed by a black box?
>
> [Project Name] is open-source subscription analytics. Connect it to Stripe, Lago, Kill Bill, or any billing source. Get MRR, churn, LTV, cohorts — computed transparently, hosted on your infrastructure, and customizable to your billing model.
>
> No percentage-of-revenue pricing. No opaque metric calculations. No sending your billing data to a third party. Just metrics you can trust because you can read the code.

---

## Cross-References

- [Market Overview](./market-overview.md) — market size and model types
- [Billing Engines](./billing-engines.md) — upstream billing engine analysis
- [Analytics Tools](./analytics-tools.md) — downstream analytics competitor analysis
- [Competitive Matrix](./competitive-matrix.md) — feature comparison and gap analysis
