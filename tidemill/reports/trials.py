"""Trial conversion reports — data, style, and plotly chart functions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import plotly.graph_objects as go

from tidemill.reports._style import COLORS, apply_period_xaxis, format_periods

if TYPE_CHECKING:
    from pandas.io.formats.style import Styler

    from tidemill.reports.client import TidemillClient


# ── data ─────────────────────────────────────────────────────────────


def funnel(tm: TidemillClient, start: str, end: str) -> dict[str, Any]:
    """Fetch trial funnel data.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.

    Returns:
        Dict with ``started``, ``converted``, ``expired``,
        ``conversion_rate`` (decimal or None).
    """
    return tm.trial_funnel(start, end)


def timeline(
    tm: TidemillClient,
    start: str,
    end: str,
    interval: str = "month",
) -> pd.DataFrame:
    """Fetch per-period trial metrics at the requested granularity.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.
        interval: ``day``, ``week``, ``month``, ``quarter``, or ``year``.

    Returns:
        DataFrame with ``period``, ``started``, ``converted``,
        ``expired``, ``conversion_rate``.  Empty if no data.
    """
    series = tm.trial_series(start, end, interval=interval)
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(series)
    df.attrs["interval"] = interval
    return df


# ── style ────────────────────────────────────────────────────────────


def style_funnel(data: dict[str, Any]) -> Styler:
    """Format funnel dict as a styled table.

    Args:
        data: Dict from :func:`funnel`.
    """
    df = pd.DataFrame(
        [
            {
                "Started": data["started"],
                "Converted": data["converted"],
                "Expired": data["expired"],
                "Conversion Rate": data["conversion_rate"],
            }
        ]
    )
    styler = cast(
        "Styler",
        df.style.format(
            {
                "Conversion Rate": lambda v: f"{v:.1%}" if v is not None else "N/A",
            }
        ),
    )
    return styler.hide(axis="index")


def style_timeline(df: pd.DataFrame) -> Styler:
    """Format monthly trial metrics as a styled table.

    Args:
        df: DataFrame from :func:`timeline`.
    """
    if len(df) == 0:
        return pd.DataFrame({"Note": ["No trial data"]}).style.hide(axis="index")
    fmt_rate = lambda v: f"{v:.0%}" if v is not None else "N/A"  # noqa: E731
    interval = df.attrs.get("interval", "month")
    display = df.copy()
    display["period"] = format_periods(display["period"], interval)
    return cast("Styler", display.set_index("period").style.format({"conversion_rate": fmt_rate}))


# ── charts ───────────────────────────────────────────────────────────


def plot_funnel(data: dict[str, Any]) -> go.Figure:
    """Trial funnel bar + conversion pie.

    Args:
        data: Dict from :func:`funnel`.
    """
    from plotly.subplots import make_subplots

    fig = make_subplots(
        rows=1,
        cols=2,
        specs=[[{"type": "xy"}, {"type": "domain"}]],
        subplot_titles=["Trial Funnel", "Trial Conversion"],
    )

    labels = ["Started", "Converted", "Expired"]
    values = [data["started"], data["converted"], data["expired"]]
    colors = [COLORS["nrr"], COLORS["converted"], COLORS["expired"]]

    fig.add_trace(
        go.Bar(
            x=labels,
            y=values,
            marker_color=colors,
            text=[str(v) for v in values],
            textposition="outside",
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    fig.update_yaxes(title_text="Count", row=1, col=1)

    if data["started"] > 0:
        converted = data["converted"]
        not_converted = data["started"] - converted
        fig.add_trace(
            go.Pie(
                labels=["Converted", "Not converted"],
                values=[converted, not_converted],
                marker_colors=[COLORS["converted"], COLORS["expired"]],
                pull=[0.05, 0],
            ),
            row=1,
            col=2,
        )

    fig.update_layout(height=450)
    return fig


def plot_timeline(df: pd.DataFrame) -> go.Figure:
    """Trial outcomes (stacked bar) and conversion rate (line) per period.

    The x-axis granularity follows the ``interval`` stashed on
    ``df.attrs`` by :func:`timeline` (defaults to ``month``).

    Args:
        df: DataFrame from :func:`timeline`.
    """
    from plotly.subplots import make_subplots

    if len(df) == 0:
        return go.Figure().update_layout(title="No trial data")

    interval = df.attrs.get("interval", "month")
    x = pd.to_datetime(df.period)
    pending = (df.started - df.converted - df.expired).clip(lower=0)

    fig = make_subplots(
        rows=2,
        cols=1,
        subplot_titles=["Trial Outcomes", "Conversion Rate"],
        vertical_spacing=0.12,
    )

    fig.add_trace(
        go.Bar(name="Converted", x=x, y=df.converted, marker_color=COLORS["converted"]),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(name="Expired", x=x, y=df.expired, marker_color=COLORS["expired"]),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(name="Pending", x=x, y=pending, marker_color=COLORS["pending"]),
        row=1,
        col=1,
    )

    rates = [r * 100 if r is not None else None for r in df.conversion_rate]
    fig.add_trace(
        go.Scatter(
            x=x,
            y=rates,
            mode="lines+markers+text",
            line={"color": COLORS["converted"], "width": 2.5},
            marker={"size": 8},
            text=[f"{r:.0f}%" if r is not None else "" for r in rates],
            textposition="top center",
            showlegend=False,
        ),
        row=2,
        col=1,
    )
    fig.add_hline(y=50, line_dash="dot", line_color=COLORS["grey"], row=2, col=1)

    fig.update_layout(barmode="stack", height=700)
    fig.update_yaxes(title_text="Count", row=1, col=1)
    fig.update_yaxes(
        title_text="Conversion Rate (%)", ticksuffix="%", range=[0, 105], row=2, col=1
    )
    apply_period_xaxis(fig, x, interval, row=1, col=1)
    apply_period_xaxis(fig, x, interval, row=2, col=1)
    return fig
