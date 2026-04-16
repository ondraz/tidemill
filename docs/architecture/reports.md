# Reports

> Pre-built charts, styled tables, and analytics for every Tidemill metric.
> Last updated: April 2026

## Overview

`tidemill.reports` provides Plotly charts and pandas Styler tables for subscription analytics. Each metric has its own submodule (`mrr`, `churn`, `retention`, `ltv`, `trials`) following a consistent three-layer pattern:

| Layer | Naming convention | Returns | Purpose |
|-------|-------------------|---------|---------|
| **Data** | `waterfall()`, `timeline()`, … | `DataFrame` or `dict` | Fetch from API, convert cents to dollars |
| **Style** | `style_waterfall()`, … | `pd.io.formats.style.Styler` | Rich table display in Jupyter |
| **Chart** | `plot_waterfall()`, … | `plotly.graph_objects.Figure` | Interactive Plotly visualisation |

## Quick start

```python
from tidemill.reports import setup, mrr, churn, retention, ltv, trials
from tidemill.reports.client import TidemillClient

setup()                          # activate Tidemill Plotly template
tm = TidemillClient()            # reads TIDEMILL_API env var

# Data → style → chart (each layer is independent)
df = mrr.waterfall(tm, "2025-09-01", "2026-04-30")
mrr.style_waterfall(df)          # styled table
mrr.plot_waterfall(df)           # Plotly figure
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TIDEMILL_API` | `http://localhost:8000` | Tidemill REST API base URL |
| `TIDEMILL_API_KEY` | *(empty)* | Bearer token (omit if auth disabled) |

## Module reference

### `tidemill.reports` (package)

```python
from tidemill.reports import setup, mrr, churn, retention, ltv, trials
```

`setup()` registers and activates the Tidemill Plotly template (`simple_white+tidemill`). Call it once at the top of a notebook or script.

---

### `tidemill.reports.client`

`TidemillClient` — thin wrapper around the Tidemill REST API. Every metric endpoint has a typed convenience method:

| Method | Returns |
|--------|---------|
| `mrr(at=None)` | MRR in cents |
| `arr(at=None)` | ARR in cents |
| `mrr_breakdown(start, end)` | List of movement dicts |
| `mrr_waterfall(start, end)` | List of monthly waterfall dicts |
| `churn(start, end, type="logo")` | Churn rate (float or None) |
| `churn_customers(start, end)` | Per-customer churn detail |
| `retention(start, end, **kw)` | Cohort retention data |
| `ltv(start, end)` | Simple LTV in cents |
| `arpu(at=None)` | ARPU in cents |
| `cohort_ltv(start, end)` | Per-cohort LTV breakdown |
| `trial_rate(start, end)` | Trial conversion rate |
| `trial_funnel(start, end)` | Funnel dict |
| `trial_series(start, end, interval)` | Time-series list |
| `sources()` | Connected billing sources |

---

### `tidemill.reports.mrr`

MRR breakdown, waterfall, and trend charts.

#### Data functions

| Function | Inputs | Returns |
|----------|--------|---------|
| `breakdown(tm, start, end)` | `TidemillClient`, ISO date range | `DataFrame` with `movement_type`, `amount_base`, `amount` |
| `waterfall(tm, start, end)` | `TidemillClient`, ISO date range | `DataFrame` with monthly starting/ending MRR and movements (dollars) |
| `movement_log(tm, start, end)` | `TidemillClient`, ISO date range | `DataFrame` with per-customer daily movements |
| `trend(tm, start, end)` | `TidemillClient`, ISO date range | `DataFrame` with `month` and `ending_mrr` (dollars) |

#### Style functions

| Function | Input | Output |
|----------|-------|--------|
| `style_waterfall(df)` | DataFrame from `waterfall` | Styler |
| `style_movement_log(df)` | DataFrame from `movement_log` | Styler |

#### Chart functions

| Function | Input | Chart type |
|----------|-------|------------|
| `plot_breakdown(df)` | DataFrame from `breakdown` | Bar chart — MRR movements |
| `plot_waterfall(df)` | DataFrame from `waterfall` | Stacked bar + ending MRR line |
| `plot_trend(df)` | DataFrame from `trend` | Area line — MRR over time |

---

### `tidemill.reports.churn`

Customer churn sets, monthly timelines, and lost MRR.

#### Data functions

| Function | Inputs | Returns |
|----------|--------|---------|
| `customer_detail(tm, start, end)` | `TidemillClient`, ISO date range | `DataFrame` with per-customer churn detail (C_start / C_churned) |
| `timeline(tm, start, end)` | `TidemillClient`, ISO date range | `DataFrame` with `month`, `logo_churn`, `revenue_churn` (decimals) |
| `monthly_lost_mrr(tm, start, end)` | `TidemillClient`, ISO date range | `DataFrame` with `month`, `churn_dollars` |

#### Style functions

| Function | Input | Output |
|----------|-------|--------|
| `style_c_start(detail)` | DataFrame from `customer_detail` | Styler — customers active at period start with MRR |
| `style_c_churned(detail)` | DataFrame from `customer_detail` | Styler — fully churned customers with lost MRR |
| `style_timeline(df)` | DataFrame from `timeline` | Styler |

#### Chart functions

| Function | Input | Chart type |
|----------|-------|------------|
| `plot_timeline(df)` | DataFrame from `timeline` | Dual line — logo + revenue churn rates |
| `plot_monthly_lost_mrr(df)` | DataFrame from `monthly_lost_mrr` | Bar chart — churned MRR per month |

---

### `tidemill.reports.retention`

Monthly NRR and GRR tracking.

#### Data functions

| Function | Inputs | Returns |
|----------|--------|---------|
| `nrr_grr(tm, start, end)` | `TidemillClient`, ISO date range | `DataFrame` with `month`, `nrr`, `grr` (decimals) |

#### Style functions

| Function | Input | Output |
|----------|-------|--------|
| `style_nrr_grr(df)` | DataFrame from `nrr_grr` | Styler |

#### Chart functions

| Function | Input | Chart type |
|----------|-------|------------|
| `plot_nrr_grr(df)` | DataFrame from `nrr_grr` | Dual line — NRR + GRR with 100% reference |

---

### `tidemill.reports.ltv`

ARPU, simple LTV, implied churn, and cohort LTV breakdowns.

#### Data functions

| Function | Inputs | Returns |
|----------|--------|---------|
| `overview(tm, start, end)` | `TidemillClient`, ISO date range | `dict` with `arpu`, `ltv` (dollars or None), `implied_churn` (decimal or None) |
| `arpu_timeline(tm, start, end)` | `TidemillClient`, ISO date range | `DataFrame` with `month`, `arpu_dollars` |
| `cohort(tm, start, end)` | `TidemillClient`, ISO date range | `DataFrame` with `cohort_month`, `customer_count`, `avg_dollars`, `total_dollars` |

#### Style functions

| Function | Input | Output |
|----------|-------|--------|
| `style_overview(data)` | dict from `overview` | Styler |
| `style_cohort(df)` | DataFrame from `cohort` | Styler |

#### Chart functions

| Function | Input | Chart type |
|----------|-------|------------|
| `plot_arpu_timeline(df)` | DataFrame from `arpu_timeline` | Area line — monthly ARPU |
| `plot_cohort(df)` | DataFrame from `cohort` | Dual bar — avg revenue + customer count per cohort |
| `plot_ltv_overview(data)` | dict from `overview` | Bar — ARPU vs LTV |

---

### `tidemill.reports.trials`

Trial funnel, conversion rates, and monthly outcomes.

#### Data functions

| Function | Inputs | Returns |
|----------|--------|---------|
| `funnel(tm, start, end)` | `TidemillClient`, ISO date range | `dict` with `started`, `converted`, `expired`, `conversion_rate` |
| `timeline(tm, start, end)` | `TidemillClient`, ISO date range | `DataFrame` with `period`, `started`, `converted`, `expired`, `conversion_rate` |

#### Style functions

| Function | Input | Output |
|----------|-------|--------|
| `style_funnel(data)` | dict from `funnel` | Styler |
| `style_timeline(df)` | DataFrame from `timeline` | Styler |

#### Chart functions

| Function | Input | Chart type |
|----------|-------|------------|
| `plot_funnel(data)` | dict from `funnel` | Bar (funnel counts) + pie (conversion rate) |
| `plot_timeline(df)` | DataFrame from `timeline` | Stacked bar (outcomes) + line (conversion rate) |

---

## Styling

### Colour palette

`tidemill.reports._style.COLORS` defines semantic colours used across all charts:

| Key | Hex | Usage |
|-----|-----|-------|
| `new` | `#0D9488` | New MRR, active subscriptions, converted trials, GRR |
| `expansion` | `#2563EB` | Expansion MRR, NRR |
| `contraction` | `#D97706` | Contraction MRR, trialing subscriptions |
| `churn` | `#DC2626` | Churned MRR, canceled subscriptions, expired trials |
| `reactivation` | `#7C3AED` | Reactivation MRR, ARPU |
| `starting_mrr` | `#94A3B8` | Starting MRR bar, grey/neutral |

### Plotly template

`setup()` registers a custom Plotly template (`simple_white+tidemill`) that provides:

- **Typography:** Inter font family, slate colour scheme
- **Layout:** centred titles, 820x520 default size, light grid lines
- **Colour scales:** teal sequential scale for heatmaps
- **Trace defaults:** `cliponaxis=False` on scatter and bar traces so data labels are never clipped at plot boundaries

---

## Notebooks

The `docs/notebooks/` directory contains Jupyter notebooks that use the reports library — each cell is typically a single report call:

| Notebook | Metric |
|----------|--------|
| `01_mrr.ipynb` | MRR breakdown, waterfall, trend |
| `02_churn.ipynb` | Customer churn sets, timeline, lost MRR |
| `03_retention.ipynb` | NRR/GRR |
| `04_ltv.ipynb` | LTV overview, ARPU timeline, cohort LTV |
| `05_trials.ipynb` | Trial funnel, monthly outcomes |
