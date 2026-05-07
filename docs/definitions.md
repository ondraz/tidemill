# Metric Definitions

> Formal definitions for every metric computed by Tidemill.
> All monetary values are stored as integer cents and converted to decimal at query boundaries.

## Time Zone Convention

**Every timestamp in Tidemill is UTC.**

All wall-clock values — stored columns, API payloads, Kafka events, CLI output,
notebook arguments — are interpreted as UTC. PostgreSQL columns are
`TIMESTAMPTZ` and Python `datetime` values are constructed with
`datetime.now(UTC)` / `datetime.fromtimestamp(..., tz=UTC)`. Bare
`YYYY-MM-DD` dates passed across the API boundary are resolved against UTC
(so `2025-09-30` expands to `2025-09-30T00:00:00Z` … `2025-09-30T23:59:59.999999Z`).

The frontend date picker intentionally treats `YYYY-MM-DD` strings as local
calendar days for display purposes only — the values sent to the API are the
raw date strings and are resolved as UTC server-side.

## Date Range Convention

**Every date range in Tidemill is closed-closed: `[start, end]` — both endpoints are inclusive.**

A range written as `2025-07-01 to 2025-09-30` covers every UTC timestamp from
`2025-07-01T00:00:00.000000Z` through `2025-09-30T23:59:59.999999Z`, inclusive
of both boundaries.

This convention applies everywhere:

- **API query parameters** (`?start=2025-07-01&end=2025-09-30`) — both dates are inclusive calendar days.
- **Python reports & notebooks** — pass the last day of the period as `end`, not the first of next month.
- **Frontend picker** — stores and displays the inclusive last day.
- **Metric SQL** — the cube filter layer coerces a bare `date` upper bound to the
  last microsecond of that day so SQL `BETWEEN` is truly inclusive against
  `TIMESTAMPTZ` columns.

Period subscripts like "period start" / "period end" in the formulas below
always refer to these inclusive boundaries.

## MRR — Monthly Recurring Revenue

The normalized monthly revenue from all active subscriptions. Annual and other non-monthly intervals are converted to a monthly equivalent.

### Current MRR

$$
\text{MRR} = \sum_{s \in S_{\text{active}}} \text{mrr}(s)
$$

where $S_{\text{active}}$ is the set of subscriptions with $\text{mrr} > 0$ at the query date, and:

$$
\text{mrr}(s) = \text{subscription\_mrr}(s) + \text{usage\_mrr}(s)
$$

#### Subscription component (committed recurring)

For licensed (non-metered) subscription items:

$$
\text{subscription\_mrr}(s) = \begin{cases}
\text{amount} & \text{if interval = month} \\
\text{amount} / 12 & \text{if interval = year} \\
\text{amount} \times 52 / 12 & \text{if interval = week}
\end{cases}
$$

Computed at subscription-event time from `price.unit_amount × quantity`. Metered items are excluded here — they feed the usage component below.

#### Usage component (trailing 3-month average)

For metered/usage-based billing, Tidemill uses the **trailing 3-month average** of finalized usage charges as the customer's recurring usage MRR — the same convention as ChartMogul / Baremetrics. This smooths month-to-month spikes and produces a stable expansion / contraction signal for bursty workloads.

$$
\text{usage\_mrr}(s) = \frac{1}{n} \sum_{m \in M_n(s)} \text{usage}(s, m)
$$

where:

- $M_n(s)$ = the most recent $n \le 3$ finalized billing months for subscription $s$
- $\text{usage}(s, m)$ = sum of `kind='usage'` invoice line items for $s$ in month $m$
- For subscriptions with fewer than 3 months of history, the mean is taken over what's present (so a month-1 customer with $40 of usage carries $40 of usage MRR rather than $13.33).
- A change in $\text{usage\_mrr}(s)$ between recomputes (one per `invoice.paid`) emits a `source='usage'` MRR movement of type `expansion` or `contraction`.

**Why trailing-3 specifically:** smoothing gives investors and operators a number that doesn't whipsaw with seasonal or one-off usage events. The 1.5-month lag is the cost; the alternative ("most recent invoice's usage") is more current but too volatile to drive churn-rate or LTV calculations.

### ARR — Annual Recurring Revenue

$$
\text{ARR} = \text{MRR} \times 12
$$

### MRR Movements

Every subscription change produces exactly one movement, categorized as:

| Movement | Trigger | Amount |
|----------|---------|--------|
| **New** | Subscription activated | $+\text{mrr}(s)$ |
| **Expansion** | Plan change with price increase | $+(\text{mrr}_{\text{new}} - \text{mrr}_{\text{prev}})$ |
| **Contraction** | Plan change with price decrease | $-(\text{mrr}_{\text{prev}} - \text{mrr}_{\text{new}})$ |
| **Churn** | Subscription churned or paused | $-\text{mrr}_{\text{prev}}$ |
| **Reactivation** | Previously churned subscription resumed | $+\text{mrr}(s)$ |

### Net New MRR

$$
\Delta\text{MRR} = \text{New} + \text{Expansion} + \text{Reactivation} - |\text{Contraction}| - |\text{Churn}|
$$

### MRR Waterfall

For each month $m$ in a range:

$$
\text{Starting MRR}_m = \text{Ending MRR}_{m-1}
$$

$$
\text{Ending MRR}_m = \text{Starting MRR}_m + \Delta\text{MRR}_m
$$

The first month's starting MRR is the snapshot MRR at the beginning of the range.

---

## Churn

### Logo Churn Rate

The fraction of customers lost in a period. A customer is considered churned when their last active subscription ends (active subscription count reaches zero).

$$
\text{Logo Churn Rate} = \frac{C_{\text{churned}}}{C_{\text{start}}}
$$

where:

- $C_{\text{churned}}$ = customers from $C_{\text{start}}$ with a logo churn event in $[\text{start}, \text{end}]$
- $C_{\text{start}}$ = customers active at period start, i.e. `first_active_at` $< \text{start}$ and (`churned_at` $\geq \text{start}$ or still active)

Only customers in $C_{\text{start}}$ can appear in the numerator — customers who both join and churn within the period are excluded.

### Revenue Churn Rate

The fraction of MRR lost to churn in a period (gross revenue churn, excludes expansion).

$$
\text{Revenue Churn Rate} = \frac{|\text{Churn MRR}|}{\text{MRR}_{\text{start}}}
$$

where:

- $|\text{Churn MRR}|$ = absolute value of MRR lost from customers in $C_{\text{start}}$ with churn events in $[\text{start}, \text{end}]$
- $\text{MRR}_{\text{start}}$ = total MRR at period start (cumulative movements before start)
- $C_{\text{start}}$ = customers active at period start (`first_active_at` $< \text{start}$)

As with logo churn, only revenue lost from customers active at period start is counted.

**Pure-usage customers and churn:** A customer on a metered-only plan has zero subscription MRR but accumulates a positive usage MRR component once their first invoice with usage charges is paid. Such customers are "active" for churn purposes the same way licensed customers are — and on subscription cancellation, the churn-MRR amount is `subscription_mrr + usage_mrr` at the moment of cancellation, so revenue churn captures both components.

---

## Usage Revenue

Distinct from MRR's usage component (which is smoothed). Usage Revenue reports the **raw monthly usage charges** as actuals, summed from `kind='usage'` invoice line items.

$$
\text{Usage Revenue}(P) = \sum_{m \in P} \sum_{s} \text{usage}(s, m)
$$

Useful for auditing meter events, reconciling against Stripe invoices, and reporting "what customers actually paid for usage this month" without the trailing-3 smoothing. Backed by the same `metric_mrr_usage_component` table — no duplicate ingestion.

---

## Retention

### Cohort Retention

Customers are assigned to a cohort based on the month of their first subscription. Retention measures what fraction of a cohort remains active in subsequent months.

$$
\text{Retention}(c, m) = \frac{A(c, m)}{|c|}
$$

where:

- $c$ = cohort (set of customers with the same first-subscription month)
- $|c|$ = cohort size (number of customers)
- $A(c, m)$ = customers from cohort $c$ who are active in month $m$
- A customer is active in a month if they have at least one active subscription during that month

### Net Revenue Retention (NRR)

Measures whether revenue from existing customers is growing or shrinking, including expansion.

$$
\text{NRR} = \frac{\text{MRR}_{\text{start}} + \text{Expansion} + \text{Reactivation} - |\text{Contraction}| - |\text{Churn}|}{\text{MRR}_{\text{start}}}
$$

- NRR > 100% means expansion outpaces churn (net negative churn)
- NRR < 100% means the customer base is shrinking in revenue

### Gross Revenue Retention (GRR)

Same as NRR but excludes expansion — measures how well existing revenue is preserved.

$$
\text{GRR} = \frac{\text{MRR}_{\text{start}} - |\text{Contraction}| - |\text{Churn}|}{\text{MRR}_{\text{start}}}
$$

- GRR is always $\leq$ 100%
- GRR = 100% means zero revenue loss from existing customers

---

## Planned (P1)

The following metrics are designed but not yet implemented.

### LTV — Customer Lifetime Value

$$
\text{LTV} = \frac{\text{ARPU}}{\text{Logo Churn Rate}}
$$

where ARPU (Average Revenue Per User) is:

$$
\text{ARPU} = \frac{\text{MRR}}{C_{\text{active}}}
$$

- $C_{\text{active}}$ = number of customers with at least one active subscription ($\text{mrr} > 0$)

**Cohort LTV** is the average cumulative revenue per customer within a cohort:

$$
\text{Cohort LTV}(c) = \frac{\sum_{i \in c} R_i}{|c|}
$$

- $R_i$ = total revenue collected from customer $i$ (sum of all paid invoices, in base currency)

### Trial Conversion Rate

Cohort-based: a trial is attributed to the period of its `trial_started` event, and its eventual outcome (converted or expired) rolls up to that same cohort — regardless of when the outcome occurs.

$$
\text{Trial Conversion Rate} = \frac{T_{\text{converted}}(c)}{T_{\text{started}}(c)}
$$

where, for a cohort period $c = [\text{start}, \text{end}]$:

- $T_{\text{started}}(c)$ = trials with `started_at` $\in c$
- $T_{\text{converted}}(c)$ = of those, trials with a non-null `converted_at` (at any time)

A March conversion of a January-cohort trial updates January's rate. Recent periods may show pending trials (neither converted nor expired yet), so their rate will move as those trials reach a terminal state.

### Quick Ratio

Measures growth efficiency — how much new revenue is generated per unit of lost revenue.

$$
\text{Quick Ratio} = \frac{\text{New} + \text{Expansion} + \text{Reactivation}}{|\text{Churn}| + |\text{Contraction}|}
$$

- Quick Ratio > 1 means the business is growing
- Quick Ratio = 4 is often cited as a benchmark for healthy SaaS

---

## Differences from ChartMogul

Tidemill's definitions are broadly aligned with ChartMogul but diverge in several places. These are intentional choices — documented here so users migrating from ChartMogul know what to expect.

### Logo Churn — same-period joiners

Both Tidemill and ChartMogul exclude customers who both join and churn within the same reporting period from the churn numerator. Tidemill enforces this by scoping the numerator to $C_{\text{start}}$ (customers with `first_active_at` $< \text{start}$), so same-period joiners never appear.

ChartMogul additionally excludes customers who churned and reactivated in the same period:

$$
\text{ChartMogul: } \text{Logo Churn Rate} = \frac{C_{\text{churned}} - C_{\text{churned\&reactivated}}}{C_{\text{start}}}
$$

**Where we still differ:** Tidemill counts a customer who churns and then reactivates within the period as a churn event. ChartMogul nets them out.

### Revenue Churn Rate — gross vs net

Tidemill defines Revenue Churn Rate as gross churn only ($|\text{Churn MRR}| / \text{MRR}_{\text{start}}$). ChartMogul defines two variants:

- **Gross MRR Churn Rate** = $(|\text{Churn}| + |\text{Contraction}|) / \text{MRR}_{\text{start}}$ — includes contraction
- **Net MRR Churn Rate** = $(\text{Churn} + \text{Contraction} - \text{Expansion}) / \text{MRR}_{\text{start}}$ — can go negative

**Why we differ:** Tidemill separates churn from contraction at the movement level. Contraction and expansion are visible in the MRR waterfall. We may add gross/net MRR churn as explicit query variants.

### Quick Ratio — reactivation

Tidemill includes reactivation in the Quick Ratio numerator. ChartMogul does not.

$$
\text{Tidemill: } \frac{\text{New} + \text{Expansion} + \text{Reactivation}}{|\text{Churn}| + |\text{Contraction}|}
$$

$$
\text{ChartMogul: } \frac{\text{New} + \text{Expansion}}{|\text{Churn}| + |\text{Contraction}|}
$$

**Why we differ:** Including reactivation gives a more complete picture of inflows vs outflows. ChartMogul treats reactivation as a separate category. Industry practice varies — neither is wrong.

### LTV — trailing average

Tidemill uses the current-period churn rate as the LTV denominator. ChartMogul uses a **6-month trailing average** of customer churn rate to smooth volatility.

**Why we differ:** The trailing average is useful but opaque — it's unclear which months are included. Tidemill's approach is more transparent. We may add a configurable lookback window.

### Trial Conversion — retroactive cohort model

Tidemill uses the same **retroactive cohort model** as ChartMogul: a trial started in January that converts in March updates January's conversion rate. The cohort is fixed by the `trial_started` event; the outcome can land at any time.

**Trade-off:** this gives a more accurate eventual conversion rate, but historical period numbers will move as late-arriving outcomes are recorded.

### Churn recognition timing

Tidemill records churn when the subscription status changes. ChartMogul offers three configurable options:

1. At cancellation (when the customer requests it)
2. At end of service period (when access actually ends)
3. When cancellation is scheduled

**Why we differ:** Tidemill currently uses option 2 (status change at period end, driven by Stripe webhook events). Making this configurable is a potential future enhancement.

### Cohort retention — revenue cohorts

ChartMogul provides both customer retention and **Net MRR Retention per cohort** (tracking how a cohort's MRR evolves over time). Tidemill currently tracks customer retention per cohort only; revenue retention is available as a global NRR/GRR metric but not broken down by cohort.

### Mid-period extrapolation

ChartMogul projects incomplete periods using:

$$
\text{Projected Rate} = \frac{\text{Total Days in Period}}{\text{Days Elapsed}} \times \text{Actual Rate}
$$

Tidemill does not extrapolate — incomplete periods show actuals only.

### ARR naming

ChartMogul calls their metric **Annual Run Rate** (Annualized Run Rate), not Annual Recurring Revenue. The formula is identical ($\text{MRR} \times 12$). Tidemill uses the more common "Annual Recurring Revenue" name.

---

## Conventions

- **Money** is stored as integer cents (`BIGINT`). All amounts are dual-column: `*_cents` (original currency) and `*_base_cents` (converted to base currency at the daily FX rate). Aggregations use base currency by default; request the `currency` dimension for per-currency breakdowns.
- **Dates** are `TIMESTAMPTZ` in the database (always UTC), `YYYY-MM-DD` in the API (resolved as UTC).
- **Period axis labels** on every chart follow a single convention, driven by the time-series granularity:
  - daily → `2025-09-15`
  - weekly → `2025-W34` (ISO week)
  - monthly → `Sep 2025`
  - quarterly → `2025-Q3`
  - yearly → `2025`

  The Python helper is `tidemill.reports._style.format_period(period, granularity)`; the TypeScript equivalent is `formatPeriod(date, granularity)` in `frontend/src/lib/formatters.ts`.
- **Churn events** are recorded when a subscription's status transitions to a terminal state. A paused subscription is treated as churned for MRR purposes and reactivated when resumed.
- **Cohort assignment** is immutable — a customer's cohort is set on their first subscription and never changes, even after churn and reactivation.
- **Segment membership** — segments filter on `customer.id` (account scope only in MVP; contract scope with per-subscription attributes is a P1 follow-up). A customer is a member of a segment iff the segment's definition evaluates to true with that customer's attributes. **NULL attribute values are treated as "not a member"** for non-null operators (`=`, `!=`, `in`, `not in`, `contains`, `>`, `<`, etc.) because the dynamic `customer_attribute` LEFT JOIN leaves the alias's columns NULL for customers without a row for the key — and NULL never equals a literal value. The `is_empty` / `is_not_empty` operators explicitly test for that NULL. In **compare mode**, a customer who satisfies multiple branches is counted in each — the CROSS JOIN duplicates each row per matching segment, preserving overlap semantics. See [segments.md](architecture/segments.md) for the full compilation model.
