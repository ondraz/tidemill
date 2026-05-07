"""LTV reports — data, style, and plotly chart functions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import plotly.graph_objects as go

from tidemill.reports._style import COLORS, apply_period_xaxis, format_periods

if TYPE_CHECKING:
    from pandas.io.formats.style import Styler

    from tidemill.reports.client import TidemillClient


# ── data ─────────────────────────────────────────────────────────────


def overview(tm: TidemillClient, start: str, end: str) -> dict[str, Any]:
    """Fetch ARPU, simple LTV, and implied churn rate.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.

    Returns:
        Dict with ``arpu`` (dollars or None), ``ltv`` (dollars or None),
        ``implied_churn`` (decimal or None).
    """
    arpu_cents = tm.arpu()
    ltv_cents = tm.ltv(start, end)

    arpu = arpu_cents / 100 if arpu_cents is not None else None
    ltv_val = ltv_cents / 100 if ltv_cents is not None else None

    implied_churn = None
    if arpu_cents and ltv_cents:
        implied_churn = arpu_cents / ltv_cents

    return {"arpu": arpu, "ltv": ltv_val, "implied_churn": implied_churn}


def arpu_timeline(tm: TidemillClient, start: str, end: str) -> pd.DataFrame:
    """Fetch monthly ARPU, MRR, and active customer counts.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.

    Returns:
        DataFrame with ``month``, ``active_customers``, ``mrr_dollars``,
        and ``arpu_dollars``.
    """
    # Snapshot at the last day of each month (closed-closed convention —
    # ``at`` is treated as an inclusive end-of-day boundary by the API).
    months = pd.date_range(start, end, freq="MS")
    rows: list[dict[str, Any]] = []
    for m in months:
        at = (m + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        arpu_cents = tm.arpu(at=at)
        mrr_cents = tm.mrr(at=at)
        customers = int(round(mrr_cents / arpu_cents)) if arpu_cents and mrr_cents else None
        rows.append(
            {
                "month": m,
                "active_customers": customers,
                "mrr_dollars": mrr_cents / 100 if mrr_cents is not None else None,
                "arpu_dollars": arpu_cents / 100 if arpu_cents is not None else None,
            }
        )

    df = pd.DataFrame(rows)
    df.attrs["interval"] = "month"
    return df


def cohort(tm: TidemillClient, start: str, end: str) -> pd.DataFrame:
    """Fetch cohort LTV data.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.

    Returns:
        DataFrame with ``cohort_month``, ``customer_count``,
        ``avg_dollars``, ``total_dollars``.  Empty if no data.
    """
    data = tm.cohort_ltv(start, end)
    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    df["cohort_month"] = pd.to_datetime(df["cohort_month"])
    df["avg_dollars"] = df.avg_revenue_per_customer.apply(lambda v: v / 100 if v else 0)
    df["total_dollars"] = df.total_revenue.apply(lambda v: v / 100 if v else 0)
    return df


# ── style ────────────────────────────────────────────────────────────


def style_overview(data: dict[str, Any]) -> Styler:
    """Format LTV overview as a styled table.

    Args:
        data: Dict from :func:`overview`.
    """
    df = pd.DataFrame(
        [
            {
                "ARPU": data["arpu"],
                "Simple LTV": data["ltv"],
                "Implied Monthly Churn": data["implied_churn"],
            }
        ]
    )
    styler = cast(
        "Styler",
        df.style.format(
            {
                "ARPU": lambda v: f"${v:,.2f}" if v is not None else "N/A",
                "Simple LTV": lambda v: f"${v:,.2f}" if v is not None else "N/A",
                "Implied Monthly Churn": lambda v: f"{v:.1%}" if v is not None else "N/A",
            }
        ),
    )
    return styler.hide(axis="index")


def style_arpu_timeline(df: pd.DataFrame) -> Styler:
    """Format monthly ARPU timeline as a styled table.

    Args:
        df: DataFrame from :func:`arpu_timeline`.
    """
    cols = ["month", "active_customers", "mrr_dollars", "arpu_dollars"]
    interval = df.attrs.get("interval", "month")
    display = df.copy()
    display["month"] = format_periods(display["month"], interval)
    styler = cast(
        "Styler",
        display[cols].style.format(
            {
                "active_customers": lambda v: f"{v:,}" if v is not None else "N/A",
                "mrr_dollars": lambda v: f"${v:,.2f}" if v is not None else "N/A",
                "arpu_dollars": lambda v: f"${v:,.2f}" if v is not None else "N/A",
            }
        ),
    )
    return styler.hide(axis="index")


def style_cohort(df: pd.DataFrame) -> Styler:
    """Format cohort LTV as a styled table.

    Args:
        df: DataFrame from :func:`cohort`.
    """
    if len(df) == 0:
        return pd.DataFrame({"Note": ["No cohort data"]}).style.hide(axis="index")
    cols = ["cohort_month", "customer_count", "avg_dollars", "total_dollars"]
    display = df.copy()
    display["cohort_month"] = format_periods(display["cohort_month"], "month")
    styler = cast(
        "Styler",
        display[cols].style.format(
            {
                "avg_dollars": "${:,.2f}",
                "total_dollars": "${:,.2f}",
            }
        ),
    )
    return styler.hide(axis="index")


# ── charts ───────────────────────────────────────────────────────────


def plot_arpu_timeline(df: pd.DataFrame) -> go.Figure:
    """Monthly ARPU trend line.

    Args:
        df: DataFrame from :func:`arpu_timeline`.
    """
    valid = df.dropna(subset=["arpu_dollars"])
    if len(valid) == 0:
        return go.Figure().update_layout(title="No ARPU data")

    interval = df.attrs.get("interval", "month")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=valid.month,
            y=valid.arpu_dollars,
            mode="lines+markers+text",
            fill="tozeroy",
            line={"color": COLORS["arpu"], "width": 2.5},
            marker={"size": 8},
            text=[f"${v:,.0f}" for v in valid.arpu_dollars],
            textposition="top center",
        )
    )
    fig.update_layout(
        title="Monthly ARPU",
        yaxis_title="ARPU ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",",
        yaxis_rangemode="tozero",
    )
    apply_period_xaxis(fig, valid.month, interval)
    return fig


def plot_cohort(df: pd.DataFrame) -> go.Figure:
    """Cohort LTV — avg revenue per customer and cohort sizes.

    Args:
        df: DataFrame from :func:`cohort`.
    """
    if len(df) == 0:
        return go.Figure().update_layout(title="No cohort data")

    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=["Avg Revenue per Customer by Cohort", "Customers per Cohort"],
    )
    cohort_x = pd.to_datetime(df.cohort_month)
    fig.add_trace(
        go.Bar(
            x=cohort_x,
            y=df.avg_dollars,
            marker_color=COLORS["arpu"],
            opacity=0.8,
            text=[f"${v:,.0f}" for v in df.avg_dollars],
            textposition="outside",
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=cohort_x,
            y=df.customer_count,
            marker_color=COLORS["nrr"],
            opacity=0.8,
            text=df.customer_count.astype(str),
            textposition="outside",
            showlegend=False,
        ),
        row=1,
        col=2,
    )
    fig.update_yaxes(title_text="Revenue ($)", tickprefix="$", tickformat=",", row=1, col=1)
    fig.update_yaxes(title_text="Count", row=1, col=2)
    fig.update_xaxes(type="date", tickformat="%b %Y", dtick="M1", row=1, col=1)
    fig.update_xaxes(type="date", tickformat="%b %Y", dtick="M1", row=1, col=2)
    fig.update_layout(height=450)
    return fig


def plot_ltv_overview(data: dict[str, Any]) -> go.Figure:
    """Indicator chart showing ARPU, implied churn, and resulting LTV.

    Args:
        data: Dict from :func:`overview`.
    """
    fig = go.Figure()
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=data["arpu"] or 0,
            title={"text": "Monthly ARPU"},
            number={"prefix": "$", "valueformat": ",.2f"},
            domain={"x": [0, 0.3], "y": [0, 1]},
        )
    )
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=(data["implied_churn"] or 0) * 100,
            title={"text": "Monthly Churn Rate"},
            number={"suffix": "%", "valueformat": ".1f"},
            domain={"x": [0.35, 0.65], "y": [0, 1]},
        )
    )
    fig.add_trace(
        go.Indicator(
            mode="number",
            value=data["ltv"] or 0,
            title={"text": "Simple LTV"},
            number={"prefix": "$", "valueformat": ",.0f"},
            domain={"x": [0.7, 1], "y": [0, 1]},
        )
    )
    fig.update_layout(height=250, title="LTV = ARPU \u00f7 Monthly Churn Rate")
    return fig
