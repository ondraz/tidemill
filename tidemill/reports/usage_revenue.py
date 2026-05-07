"""Usage revenue reports — finalized monthly metered charges (actuals).

Distinct from the trailing-3m usage component baked into MRR: this module
exposes the raw monthly numbers per customer, which is what you want when
auditing meter events or reconciling against Stripe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
import plotly.graph_objects as go

from tidemill.reports._style import COLORS, apply_period_xaxis

if TYPE_CHECKING:
    from tidemill.reports.client import TidemillClient


def total(tm: TidemillClient, start: str, end: str) -> dict[str, Any]:
    """Total finalized usage revenue for the period.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start (inclusive).
        end: ISO date string for period end (inclusive).

    Returns:
        Dict with ``revenue`` in dollars.
    """
    cents = tm.usage_revenue(start, end)
    return {"revenue": (cents or 0) / 100}


def series(
    tm: TidemillClient,
    start: str,
    end: str,
    interval: str = "month",
) -> pd.DataFrame:
    """Usage revenue per period.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.
        interval: Bucket size — ``day``, ``week``, ``month``, ``quarter``,
            or ``year``.

    Returns:
        DataFrame with ``period`` (datetime) and ``revenue`` (dollars).
    """
    raw = tm.usage_revenue_series(start, end, interval=interval)
    df = pd.DataFrame(raw)
    if df.empty:
        return pd.DataFrame(columns=["period", "revenue"])
    df["revenue"] = df["revenue"] / 100
    df["period"] = pd.to_datetime(df["period"])
    df.attrs["interval"] = interval
    return df.sort_values("period").reset_index(drop=True)


def by_customer(tm: TidemillClient, start: str, end: str) -> pd.DataFrame:
    """Per-customer usage revenue for the period, sorted high to low.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.

    Returns:
        DataFrame with ``customer_id`` and ``revenue`` (dollars).
    """
    raw = tm.usage_revenue_by_customer(start, end)
    df = pd.DataFrame(raw)
    if df.empty:
        return pd.DataFrame(columns=["customer_id", "revenue"])
    df["revenue"] = df["revenue"] / 100
    return df.sort_values("revenue", ascending=False).reset_index(drop=True)


def plot_series(df: pd.DataFrame) -> go.Figure:
    """Bar chart of usage revenue per period.

    Args:
        df: DataFrame from :func:`series`.
    """
    interval = df.attrs.get("interval", "month")
    fig = go.Figure(
        go.Bar(
            x=df.period,
            y=df.revenue,
            marker_color=COLORS["expansion"],
            text=[f"${v:,.0f}" for v in df.revenue],
            textposition="outside",
        )
    )
    fig.update_layout(
        title="Usage Revenue (Actuals)",
        yaxis_title="Revenue ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",",
    )
    apply_period_xaxis(fig, df.period, interval)
    return fig


def style_total(data: dict[str, Any]) -> pd.io.formats.style.Styler:
    """Format usage revenue total as a one-row table.

    Args:
        data: Dict from :func:`total`.
    """
    df = pd.DataFrame([{"Usage Revenue": data["revenue"]}])
    return df.style.format("${:,.2f}").hide(axis="index")


def style_by_customer(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """Format per-customer usage revenue as a styled table.

    Args:
        df: DataFrame from :func:`by_customer`.
    """
    return df.style.format({"revenue": "${:,.2f}"}).hide(axis="index")
