"""Shared styling constants and Plotly template for reports."""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

# ── Tidemill colour palette ─────────────────────────────────────────
# Warm orange-based palette for financial / SaaS analytics dashboards.

COLORS: dict[str, str] = {
    # MRR movements
    "new": "#16A34A",  # green-600
    "expansion": "#2563EB",  # blue-600
    "contraction": "#EAB308",  # yellow-500
    "churn": "#DC2626",  # red-600
    "reactivation": "#8B5CF6",  # violet-500
    "starting_mrr": "#78716C",  # stone-500
    # subscription status
    "active": "#16A34A",  # green-600
    "canceled": "#DC2626",  # red-600
    "trialing": "#F59E0B",  # amber-500
    "past_due": "#EA580C",  # orange-600
    # trials
    "converted": "#16A34A",  # green-600
    "expired": "#DC2626",  # red-600
    "pending": "#78716C",  # stone-500
    # retention
    "nrr": "#2563EB",  # blue-600
    "grr": "#16A34A",  # green-600
    # churn lines
    "logo_churn": "#DC2626",  # red-600
    "revenue_churn": "#F59E0B",  # amber-500
    # other
    "arpu": "#8B5CF6",  # violet-500
    "grey": "#78716C",  # stone-500
}

# Default colour cycle for multi-series charts.
COLORWAY: list[str] = [
    "#F59E0B",  # amber
    "#2563EB",  # blue
    "#16A34A",  # green
    "#8B5CF6",  # violet
    "#DC2626",  # red
    "#0891B2",  # cyan
    "#DB2777",  # pink
    "#84CC16",  # lime
    "#78716C",  # stone
]

# ── Plotly template ─────────────────────────────────────────────────

tidemill_template = go.layout.Template(
    layout=go.Layout(
        font_family="Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Arial, sans-serif",
        font_size=13,
        font_color="#44403C",  # stone-700
        title_font_size=16,
        title_font_color="#1C1917",  # stone-900
        title_x=0.5,
        title_y=0.97,
        colorway=COLORWAY,
        colorscale_sequential=[
            [0.0, "#FFF7ED"],  # orange-50
            [0.25, "#FED7AA"],  # orange-200
            [0.5, "#FB923C"],  # orange-400
            [0.75, "#EA580C"],  # orange-600
            [1.0, "#431407"],  # orange-950
        ],
        colorscale_sequentialminus=[
            [0.0, "#431407"],  # orange-950
            [1.0, "#FFF7ED"],  # orange-50
        ],
        coloraxis_colorbar=dict(outlinewidth=0, ticklen=6, tickwidth=1),
        xaxis=dict(
            showgrid=True,
            gridcolor="#E7E5E4",  # stone-200
            title_standoff=8,
            linecolor="#D6D3D1",  # stone-300
            zeroline=False,
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#E7E5E4",  # stone-200
            title_standoff=8,
            linecolor="#D6D3D1",  # stone-300
            zeroline=False,
        ),
        margin=dict(t=60, b=40, l=60, r=60),
        bargap=0.25,
        width=820,
        height=520,
        legend=dict(
            font_size=12,
            bgcolor="rgba(255,255,255,0)",
        ),
        hoverlabel=dict(
            bgcolor="white",
            font_size=12,
            font_color="#44403C",  # stone-700
        ),
    ),
    data=dict(
        scatter=[dict(type="scatter", line_width=2.5, cliponaxis=False)],
        bar=[dict(type="bar", marker_line_width=0, cliponaxis=False)],
    ),
)


def setup() -> None:
    """Register and activate the Tidemill plotly template."""
    pio.templates["tidemill"] = tidemill_template
    pio.templates.default = "simple_white+tidemill"
    pio.renderers.default = "plotly_mimetype+notebook_connected"


# ── Period axis formatting ──────────────────────────────────────────
#
# Every chart that plots a time series renders period labels in this
# canonical style so axes stay consistent across reports.
#
#   day       → ``2025-09-15``
#   week      → ``2025-W34`` (ISO week)
#   month     → ``Sep 2025``
#   quarter   → ``2025-Q3``
#   year      → ``2025``


def format_period(period: Any, granularity: str = "month") -> str:
    """Format a period timestamp for chart axis labels.

    Args:
        period: Anything pandas can parse into a timestamp (ISO string,
            ``datetime``, ``pd.Timestamp``, ``pd.Period``).
        granularity: One of ``day``, ``week``, ``month``, ``quarter``,
            ``year``.  Defaults to ``month``.

    Returns:
        A short human-readable label suitable for an x-axis tick.
    """
    ts = pd.Timestamp(period) if not isinstance(period, pd.Timestamp) else period
    g = granularity.lower()
    if g == "month":
        return ts.strftime("%b %Y")
    if g == "week":
        iso_year, iso_week, _ = ts.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if g == "quarter":
        q = (ts.month - 1) // 3 + 1
        return f"{ts.year}-Q{q}"
    if g == "year":
        return ts.strftime("%Y")
    return ts.strftime("%Y-%m-%d")


def format_periods(periods: Any, granularity: str = "month") -> list[str]:
    """Vectorised :func:`format_period` for a sequence of timestamps."""
    return [format_period(p, granularity) for p in periods]


def apply_period_xaxis(
    fig: go.Figure,
    periods: Any,
    granularity: str = "month",
    **update_xaxes_kwargs: Any,
) -> go.Figure:
    """Configure the x-axis of a time-series chart for a given granularity.

    Keeps the axis temporal (so Plotly handles ordering, zoom, and
    hover) and applies the canonical tick format — ``Sep 2025`` for
    months, ``2025-W34`` for ISO weeks, ``2025-Q3`` for quarters, etc.

    Args:
        fig: Plotly figure whose x-axis should be configured.
        periods: Iterable of period timestamps plotted on the x-axis.
            Required for ``quarter`` (d3 has no quarter token, so we
            supply explicit tick labels); used for boundary calculation
            otherwise.
        granularity: ``day``, ``week``, ``month``, ``quarter``, or
            ``year``.
        **update_xaxes_kwargs: Forwarded to ``fig.update_xaxes``.

    Returns:
        The same figure for chaining.
    """
    g = granularity.lower()
    base: dict[str, Any] = {"type": "date"}
    if g == "day":
        base["tickformat"] = "%Y-%m-%d"
    elif g == "week":
        # d3 %G = ISO week year, %V = ISO week number (zero-padded).
        base["tickformat"] = "%G-W%V"
    elif g == "month":
        base["tickformat"] = "%b %Y"
        base["dtick"] = "M1"
    elif g == "year":
        base["tickformat"] = "%Y"
        base["dtick"] = "M12"
    elif g == "quarter":
        ts = pd.to_datetime(list(periods))
        base["tickmode"] = "array"
        base["tickvals"] = list(ts)
        base["ticktext"] = [format_period(t, "quarter") for t in ts]
    base.update(update_xaxes_kwargs)
    fig.update_xaxes(**base)
    return fig
