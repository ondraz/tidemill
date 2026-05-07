"""Retention reports — data, style, and plotly chart functions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import plotly.graph_objects as go

from tidemill.reports._style import COLORS, apply_period_xaxis, format_period, format_periods

if TYPE_CHECKING:
    from pandas.io.formats.style import Styler

    from tidemill.reports.client import TidemillClient


# ── data ─────────────────────────────────────────────────────────────


def cohort(tm: TidemillClient, start: str, end: str) -> pd.DataFrame:
    """Fetch cohort retention matrix as a pivot table.

    Each row is a cohort (customers who first activated in that calendar
    month); each column ``M0, M1, ... Mn`` is the fraction of the cohort
    still active ``n`` months later.

    Args:
        tm: Tidemill API client.
        start: ISO date string — earliest cohort month to include.
        end: ISO date string — latest cohort month to include.

    Returns:
        DataFrame indexed by ``cohort_month``, with ``cohort_size`` and
        ``M0 .. Mn`` columns (retention as decimals).
    """
    rows = tm.cohort_matrix(start, end)
    all_months = pd.period_range(start=start, end=end, freq="M")

    df = pd.DataFrame(rows)
    if not df.empty:
        df["cohort_month"] = pd.to_datetime(df["cohort_month"]).dt.to_period("M")
        df["active_month"] = pd.to_datetime(df["active_month"]).dt.to_period("M")
        df["months_since"] = (df["active_month"] - df["cohort_month"]).apply(lambda x: x.n)
        df = df[df["months_since"] >= 0]
        df["retention"] = df["active_count"] / df["cohort_size"]

        size_by_cohort = df.groupby("cohort_month")["cohort_size"].first()
        pivot = df.pivot_table(
            index="cohort_month",
            columns="months_since",
            values="retention",
            aggfunc="first",
        )
        pivot.columns = [f"M{int(c)}" for c in pivot.columns]
    else:
        size_by_cohort = pd.Series(dtype="int64")
        pivot = pd.DataFrame()

    pivot = pivot.reindex(all_months).sort_index()
    pivot.insert(0, "cohort_size", size_by_cohort.reindex(all_months).fillna(0).astype(int))
    pivot.index = [format_period(p.to_timestamp(), "month") for p in pivot.index]
    pivot.index.name = "cohort_month"
    return cast("pd.DataFrame", pivot)


def nrr_grr(tm: TidemillClient, start: str, end: str) -> pd.DataFrame:
    """Fetch monthly NRR and GRR from Tidemill.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.

    Returns:
        DataFrame with ``month``, ``nrr``, ``grr`` (as decimals).
    """
    # Query each month closed-closed ``[first-of-month, last-of-month]`` per
    # Tidemill's date-range convention (see docs/definitions.md).
    months = pd.date_range(start, end, freq="MS")
    rows: list[dict[str, Any]] = []
    for m in months:
        s = m.strftime("%Y-%m-%d")
        e = (m + pd.offsets.MonthEnd(0)).strftime("%Y-%m-%d")
        nrr_val = tm.retention(s, e, query_type="nrr")
        grr_val = tm.retention(s, e, query_type="grr")
        rows.append(
            {
                "month": m,
                "nrr": nrr_val,
                "grr": grr_val,
            }
        )
    df = pd.DataFrame(rows)
    df.attrs["interval"] = "month"
    return df


# ── style ────────────────────────────────────────────────────────────


def style_cohort(df: pd.DataFrame) -> Styler:
    """Format cohort retention as a styled heatmap-like table.

    Args:
        df: DataFrame from :func:`cohort`.
    """
    if df.empty:
        return df.style
    pct_cols = [c for c in df.columns if c.startswith("M")]
    fmt_pct = lambda v: f"{v:.0%}" if pd.notna(v) else ""  # noqa: E731
    styler = cast(
        "Styler",
        df.style.format({c: fmt_pct for c in pct_cols}).format({"cohort_size": "{:,.0f}"}),
    )
    return styler.background_gradient(
        subset=pct_cols,
        cmap="Greens",
        vmin=0,
        vmax=1,
    )


def style_nrr_grr(df: pd.DataFrame) -> Styler:
    """Format NRR/GRR as a styled table with percentage formatting.

    Args:
        df: DataFrame from :func:`nrr_grr`.
    """
    fmt_pct = lambda v: f"{v:.1%}" if v is not None else "N/A"  # noqa: E731
    interval = df.attrs.get("interval", "month")
    display = df.copy()
    display["month"] = format_periods(display["month"], interval)
    return cast(
        "Styler", display.set_index("month").style.format({"nrr": fmt_pct, "grr": fmt_pct})
    )


# ── charts ───────────────────────────────────────────────────────────


def plot_cohort(df: pd.DataFrame) -> go.Figure:
    """Cohort retention heatmap.

    Args:
        df: DataFrame from :func:`cohort`.
    """
    pct_cols = [c for c in df.columns if c.startswith("M")]
    z = df[pct_cols].to_numpy() * 100
    text = [[f"{v:.0%}" if pd.notna(v) else "" for v in row] for row in df[pct_cols].to_numpy()]

    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=pct_cols,
            y=[f"{idx} (n={int(s)})" for idx, s in zip(df.index, df["cohort_size"], strict=True)],
            text=text,
            texttemplate="%{text}",
            colorscale="Greens",
            zmin=0,
            zmax=100,
            colorbar={"title": "Retention (%)", "ticksuffix": "%"},
            hovertemplate="Cohort %{y}<br>%{x}: %{z:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title="Cohort Retention",
        xaxis_title="Months since cohort start",
        yaxis_title="Cohort",
        yaxis_autorange="reversed",
        height=60 + 30 * len(df),
    )
    return fig


def plot_nrr_grr(df: pd.DataFrame) -> go.Figure:
    """Monthly NRR and GRR line chart.

    Args:
        df: DataFrame from :func:`nrr_grr`.
    """
    interval = df.attrs.get("interval", "month")
    x = df.month
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=df.nrr.apply(lambda v: v * 100 if v is not None else None),
            name="NRR",
            mode="lines+markers+text",
            line={"color": COLORS["nrr"], "width": 2.5},
            marker={"size": 8},
            text=[f"{v * 100:.0f}%" if v is not None else "" for v in df.nrr],
            textposition="top center",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=df.grr.apply(lambda v: v * 100 if v is not None else None),
            name="GRR",
            mode="lines+markers+text",
            line={"color": COLORS["grr"], "width": 2.5, "dash": "dash"},
            marker={"size": 8, "symbol": "square"},
            text=[f"{v * 100:.0f}%" if v is not None else "" for v in df.grr],
            textposition="bottom center",
        )
    )
    fig.add_hline(y=100, line_dash="dot", line_color=COLORS["grey"], annotation_text="100%")
    fig.update_layout(
        title="Monthly Revenue Retention",
        yaxis_title="Retention (%)",
        yaxis_ticksuffix="%",
    )
    apply_period_xaxis(fig, x, interval)
    return fig
