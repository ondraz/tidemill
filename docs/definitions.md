# Metric Definitions

> Formal definitions for every metric computed by Tidemill.
> All monetary values are stored as integer cents and converted to decimal at query boundaries.

## MRR — Monthly Recurring Revenue

The normalized monthly revenue from all active subscriptions. Annual and other non-monthly intervals are converted to a monthly equivalent.

### Current MRR

$$
\text{MRR} = \sum_{s \in S_{\text{active}}} \text{mrr}(s)
$$

where $S_{\text{active}}$ is the set of subscriptions with $\text{mrr} > 0$ at the query date, and:

$$
\text{mrr}(s) = \begin{cases}
\text{amount} & \text{if interval = month} \\
\text{amount} / 12 & \text{if interval = year} \\
\text{amount} \times 52 / 12 & \text{if interval = week}
\end{cases}
$$

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

- $C_{\text{churned}}$ = customers from $C_{\text{start}}$ with a logo churn event in $[\text{start}, \text{end})$
- $C_{\text{start}}$ = customers active at period start, i.e. `first_active_at` $< \text{start}$ and (`churned_at` $\geq \text{start}$ or still active)

Only customers in $C_{\text{start}}$ can appear in the numerator — customers who both join and churn within the period are excluded.

### Revenue Churn Rate

The fraction of MRR lost to churn in a period (gross revenue churn, excludes expansion).

$$
\text{Revenue Churn Rate} = \frac{|\text{Churn MRR}|}{\text{MRR}_{\text{start}}}
$$

where:

- $|\text{Churn MRR}|$ = absolute value of MRR lost from customers in $C_{\text{start}}$ with churn events in $[\text{start}, \text{end})$
- $\text{MRR}_{\text{start}}$ = total MRR at period start (cumulative movements before start)
- $C_{\text{start}}$ = customers active at period start (`first_active_at` $< \text{start}$)

As with logo churn, only revenue lost from customers active at period start is counted.

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

$$
\text{Trial Conversion Rate} = \frac{T_{\text{converted}}}{T_{\text{started}}}
$$

where $T_{\text{started}}$ and $T_{\text{converted}}$ are counts of trial events in the period.

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

### Trial Conversion — point-in-time vs retroactive

Tidemill counts conversions that occur within the query period. ChartMogul uses a **retroactive cohort model**: a trial started in January that converts in March updates January's conversion rate.

**Why we differ:** Point-in-time is simpler and stable (the number for a given period doesn't change). ChartMogul's approach gives a more accurate eventual conversion rate but means historical numbers keep changing.

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
- **Dates** are `TIMESTAMPTZ` in the database, `YYYY-MM-DD` in the API.
- **Churn events** are recorded when a subscription's status transitions to a terminal state. A paused subscription is treated as churned for MRR purposes and reactivated when resumed.
- **Cohort assignment** is immutable — a customer's cohort is set on their first subscription and never changes, even after churn and reactivation.
