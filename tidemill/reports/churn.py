"""Churn reports — data, style, and plotly chart functions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
import plotly.graph_objects as go

from tidemill.reports._style import COLORS

if TYPE_CHECKING:
    from tidemill.reports.client import TidemillClient


# ── data ─────────────────────────────────────────────────────────────


def customer_detail(
    tm: TidemillClient,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Per-customer churn detail for the measurement window.

    Args:
        tm: Tidemill API client.
        start: ISO date string for window start.
        end: ISO date string for window end.

    Returns:
        DataFrame with one row per active-at-start customer.
    """
    data = tm.churn_customers(start, end)
    if not data:
        cols = [
            "customer",
            "customer_name",
            "active_at_start",
            "fully_churned",
            "churned_mrr_cents",
            "starting_mrr_cents",
        ]
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(data).rename(columns={"customer_id": "customer"})
    if "customer_name" not in df.columns:
        df["customer_name"] = None
    df["customer_name"] = df["customer_name"].fillna("")
    return df.sort_values("customer").reset_index(drop=True)


def timeline(tm: TidemillClient, start: str, end: str) -> pd.DataFrame:
    """Fetch monthly logo and revenue churn rates.

    Args:
        tm: Tidemill API client.
        start: ISO date for first month of churn measurement.
        end: ISO date for last month boundary.

    Returns:
        DataFrame with ``month``, ``logo_churn``, ``revenue_churn``
        (as decimals, e.g. 0.05 = 5%).
    """
    months = pd.date_range(start, end, freq="MS")
    rows: list[dict[str, Any]] = []
    for i in range(len(months) - 1):
        s = months[i].strftime("%Y-%m-%d")
        e = months[i + 1].strftime("%Y-%m-%d")
        logo = tm.churn(s, e, type="logo")
        revenue = tm.churn(s, e, type="revenue")
        rows.append(
            {
                "month": months[i].strftime("%Y-%m"),
                "logo_churn": float(logo) if logo is not None else None,
                "revenue_churn": float(revenue) if revenue is not None else None,
            }
        )
    return pd.DataFrame(rows)


def monthly_lost_mrr(tm: TidemillClient, start: str, end: str) -> pd.DataFrame:
    """Fetch churned MRR per month from the MRR waterfall.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.

    Returns:
        DataFrame with ``month`` and ``churn_dollars``.
    """
    raw = tm.mrr_waterfall(start, end)
    df = pd.DataFrame(raw)
    df["churn_dollars"] = df["churn"].apply(lambda c: abs(c) / 100)
    return df


# ── style ────────────────────────────────────────────────────────────


def style_timeline(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """Format monthly churn rates as a styled table.

    Args:
        df: DataFrame from :func:`timeline`.
    """
    return df.set_index("month").style.format(
        {
            "logo_churn": lambda v: f"{v:.1%}" if v is not None else "N/A",
            "revenue_churn": lambda v: f"{v:.1%}" if v is not None else "N/A",
        }
    )


def style_c_start(detail: pd.DataFrame) -> pd.io.formats.style.Styler:
    """C_start — customers active at period start, with starting MRR.

    Args:
        detail: DataFrame from :func:`customer_detail`.
    """
    df = detail[["customer", "starting_mrr_cents"]].copy()
    if "customer_name" in detail.columns:
        df.insert(1, "customer_name", detail["customer_name"])
    df["starting_mrr"] = df.starting_mrr_cents.apply(lambda c: f"${c / 100:,.2f}")
    total = int(df.starting_mrr_cents.sum())
    totals = pd.DataFrame(
        [{"customer": "TOTAL", "customer_name": "", "starting_mrr": f"${total / 100:,.2f}"}]
    )
    display = pd.concat([df, totals], ignore_index=True)
    cols = (
        ["customer", "customer_name", "starting_mrr"]
        if "customer_name" in display.columns
        else ["customer", "starting_mrr"]
    )
    return (
        display[cols]
        .style.set_caption(f"C_start: {len(detail)} customers, ${total / 100:,.2f} MRR")
        .hide(axis="index")
    )


def style_c_churned(detail: pd.DataFrame) -> pd.io.formats.style.Styler:
    """C_churned — customers who fully churned, with churned MRR.

    Args:
        detail: DataFrame from :func:`customer_detail`.
    """
    churned = detail[detail.fully_churned].copy()
    df = churned[["customer", "starting_mrr_cents", "churned_mrr_cents"]].copy()
    if "customer_name" in churned.columns:
        df.insert(1, "customer_name", churned["customer_name"])
    df["starting_mrr"] = df.starting_mrr_cents.apply(lambda c: f"${c / 100:,.2f}")
    df["churned_mrr"] = df.churned_mrr_cents.apply(lambda c: f"${c / 100:,.2f}")
    total_start = int(df.starting_mrr_cents.sum())
    total_churned = int(df.churned_mrr_cents.sum())
    totals = pd.DataFrame(
        [
            {
                "customer": "TOTAL",
                "customer_name": "",
                "starting_mrr": f"${total_start / 100:,.2f}",
                "churned_mrr": f"${total_churned / 100:,.2f}",
            }
        ]
    )
    display = pd.concat([df, totals], ignore_index=True)
    cols = (
        ["customer", "customer_name", "starting_mrr", "churned_mrr"]
        if "customer_name" in display.columns
        else ["customer", "starting_mrr", "churned_mrr"]
    )
    return (
        display[cols]
        .style.set_caption(
            f"C_churned: {len(churned)} customers, ${total_churned / 100:,.2f} lost MRR"
        )
        .hide(axis="index")
    )


# ── charts ───────────────────────────────────────────────────────────


def plot_timeline(df: pd.DataFrame) -> go.Figure:
    """Monthly logo + revenue churn rate lines.

    Args:
        df: DataFrame from :func:`timeline`.
    """
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df.month,
            y=df.logo_churn.apply(lambda v: v * 100 if v is not None else None),
            name="Logo Churn",
            mode="lines+markers+text",
            line={"color": COLORS["logo_churn"], "width": 2},
            marker={"size": 8},
            text=[f"{v * 100:.1f}%" if v is not None else "" for v in df.logo_churn],
            textposition="top center",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df.month,
            y=df.revenue_churn.apply(lambda v: v * 100 if v is not None else None),
            name="Revenue Churn",
            mode="lines+markers+text",
            line={"color": COLORS["revenue_churn"], "width": 2, "dash": "dash"},
            marker={"size": 8, "symbol": "square"},
            text=[f"{v * 100:.1f}%" if v is not None else "" for v in df.revenue_churn],
            textposition="bottom center",
        )
    )
    fig.update_layout(
        title="Monthly Churn Rate",
        yaxis_title="Churn Rate (%)",
        yaxis_ticksuffix="%",
        yaxis_rangemode="tozero",
    )
    return fig


def plot_monthly_lost_mrr(df: pd.DataFrame) -> go.Figure:
    """Bar chart of churned MRR per month.

    Args:
        df: DataFrame from :func:`monthly_lost_mrr`.
    """
    fig = go.Figure(
        go.Bar(
            x=df.month,
            y=df.churn_dollars,
            marker_color=COLORS["churn"],
            opacity=0.8,
            text=[f"${v:,.0f}" if v > 0 else "" for v in df.churn_dollars],
            textposition="outside",
        )
    )
    fig.update_layout(
        title="Monthly Churned MRR",
        yaxis_title="Lost MRR ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",",
        yaxis_rangemode="tozero",
    )
    return fig
