"""Usage revenue reports — finalized monthly metered charges (actuals).

Distinct from the trailing-3m usage component baked into MRR: this module
exposes the raw monthly numbers per customer, which is what you want when
auditing meter events or reconciling against Stripe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import plotly.graph_objects as go
from pandas.io.formats.style import Styler

from tidemill.reports._style import COLORS, apply_period_xaxis, plot_grouped_bars

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
    by_source: bool = False,
) -> pd.DataFrame:
    """Usage revenue per period.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.
        interval: Bucket size — ``day``, ``week``, ``month``, ``quarter``,
            or ``year``.
        by_source: When True, split revenue per billing source (the frame
            gains a ``source`` column); :func:`plot_series` then renders
            grouped bars.

    Returns:
        DataFrame with ``period`` (datetime) and ``revenue`` (dollars), plus
        ``source`` when *by_source*.
    """
    if by_source:
        frames: list[pd.DataFrame] = []
        for src in tm.source_types():
            raw = tm.usage_revenue_series(start, end, interval=interval, source=src)
            if not raw:
                continue
            part = pd.DataFrame(raw)
            part["revenue"] = part["revenue"] / 100
            part["period"] = pd.to_datetime(part["period"])
            part["source"] = src
            frames.append(part[["period", "revenue", "source"]])
        df = (
            pd.concat(frames, ignore_index=True)
            if frames
            else pd.DataFrame(columns=["period", "revenue", "source"])
        )
        df.attrs["interval"] = interval
        return df.sort_values("period").reset_index(drop=True)

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

    When *df* carries a ``source`` column (from ``series(..., by_source=True)``)
    the periods are drawn as grouped bars, one colour per billing source.

    Args:
        df: DataFrame from :func:`series`.
    """
    interval = df.attrs.get("interval", "month")
    if "source" in df.columns:
        return plot_grouped_bars(
            df,
            x_col="period",
            y_col="revenue",
            title="Usage Revenue by Source",
            yaxis_title="Revenue ($)",
            interval=interval,
        )
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


def style_total(data: dict[str, Any]) -> Styler:
    """Format usage revenue total as a one-row table.

    Args:
        data: Dict from :func:`total`.
    """
    df = pd.DataFrame([{"Usage Revenue": data["revenue"]}])
    styler = cast(Styler, df.style.format("${:,.2f}"))
    return styler.hide(axis="index")


def style_by_customer(df: pd.DataFrame) -> Styler:
    """Format per-customer usage revenue as a styled table.

    Args:
        df: DataFrame from :func:`by_customer`.
    """
    styler = cast(Styler, df.style.format({"revenue": "${:,.2f}"}))
    return styler.hide(axis="index")
