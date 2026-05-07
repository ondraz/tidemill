"""MRR reports — data, style, and plotly chart functions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import plotly.graph_objects as go

from tidemill.reports._style import COLORS, apply_period_xaxis, format_periods

if TYPE_CHECKING:
    from pandas.io.formats.style import Styler

    from tidemill.reports.client import TidemillClient


# ── data ─────────────────────────────────────────────────────────────


def snapshot(tm: TidemillClient, at: str | None = None) -> dict[str, Any]:
    """Current MRR and ARR.

    Args:
        tm: Tidemill API client.
        at: Optional ISO date to query at a specific point.

    Returns:
        Dict with ``mrr`` and ``arr`` in dollars.
    """
    mrr_cents = tm.mrr(at=at)
    arr_cents = tm.arr(at=at)
    return {
        "mrr": mrr_cents / 100,
        "arr": arr_cents / 100,
    }


def usage_breakdown(tm: TidemillClient) -> dict[str, Any]:
    """Split current MRR into subscription and usage (trailing-3m) components.

    Useful for sanity-checking how much of headline MRR is the smoothed
    metered component vs. committed licensed recurring.

    Args:
        tm: Tidemill API client.

    Returns:
        Dict with ``subscription_mrr``, ``usage_mrr``, ``mrr``, and
        ``usage_share`` (0.0–1.0) — all dollar amounts except the share.
    """
    components = tm.mrr_components()
    sub_cents = int(components.get("subscription_mrr") or 0)
    usage_cents = int(components.get("usage_mrr") or 0)
    total_cents = int(components.get("mrr") or 0) or (sub_cents + usage_cents)
    return {
        "subscription_mrr": sub_cents / 100,
        "usage_mrr": usage_cents / 100,
        "mrr": total_cents / 100,
        "usage_share": (usage_cents / total_cents) if total_cents else 0.0,
    }


def style_usage_breakdown(data: dict[str, Any]) -> pd.io.formats.style.Styler:
    """Format the usage/subscription MRR split as a one-row table.

    Args:
        data: Dict from :func:`usage_breakdown`.
    """
    df = pd.DataFrame(
        [
            {
                "Subscription MRR": data["subscription_mrr"],
                "Usage MRR": data["usage_mrr"],
                "Total MRR": data["mrr"],
                "Usage share": data["usage_share"],
            }
        ]
    )
    return df.style.format(
        {
            "Subscription MRR": "${:,.2f}",
            "Usage MRR": "${:,.2f}",
            "Total MRR": "${:,.2f}",
            "Usage share": "{:.1%}",
        }
    ).hide(axis="index")


def breakdown(tm: TidemillClient, start: str, end: str) -> pd.DataFrame:
    """Fetch MRR movement breakdown.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.

    Returns:
        DataFrame with ``movement_type``, ``amount_base``, ``amount``.
    """
    data = tm.mrr_breakdown(start, end)
    df = pd.DataFrame(data)
    df["amount"] = df["amount_base"] / 100
    return df


def waterfall(tm: TidemillClient, start: str, end: str, interval: str = "month") -> pd.DataFrame:
    """Fetch the MRR waterfall, bucketed by the given interval.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.
        interval: Bucket size — ``day``, ``week``, ``month``, ``quarter``,
            or ``year``.

    Returns:
        DataFrame with one row per period (``period`` column is the
        inclusive start date of the bucket), amounts in dollars.
    """
    raw = tm.mrr_waterfall(start, end, interval=interval)
    df = pd.DataFrame(raw)
    money_cols = [
        "starting_mrr",
        "new",
        "expansion",
        "contraction",
        "churn",
        "reactivation",
        "net_change",
        "ending_mrr",
    ]
    for col in money_cols:
        df[col] = df[col] / 100
    df["period"] = pd.to_datetime(df["period"])
    df.attrs["interval"] = interval
    return df


def movement_log(tm: TidemillClient, start: str, end: str) -> pd.DataFrame:
    """Per-customer MRR movements with timestamps, split by month.

    Fetches the MRR breakdown dimensioned by ``customer_id`` and
    ``customer_name`` with daily granularity so every individual movement
    that feeds the waterfall chart is visible and auditable.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.

    Returns:
        DataFrame with ``month``, ``date``, ``customer_name``,
        ``customer_id``, ``movement_type``, ``amount`` (dollars),
        sorted by date then movement type.
    """
    cols = ["month", "date", "customer_name", "customer_id", "movement_type", "amount"]
    data = tm.get(
        "/api/metrics/mrr/breakdown",
        start=start,
        end=end,
        dimensions=["customer_id", "customer_name"],
        granularity="day",
    )
    if not data:
        return pd.DataFrame(columns=cols)

    df = pd.DataFrame(data)
    df["amount"] = df["amount_base"] / 100
    df["date"] = pd.to_datetime(df["period"]).dt.strftime("%Y-%m-%d")
    df["month"] = pd.to_datetime(df["period"]).dt.strftime("%Y-%m")
    df["customer_name"] = df["customer_name"].fillna("")

    type_order = {"new": 0, "expansion": 1, "reactivation": 2, "contraction": 3, "churn": 4}
    df["_order"] = df["movement_type"].map(type_order).fillna(5)
    df = df.sort_values(["date", "_order", "customer_name"]).reset_index(drop=True)
    return cast("pd.DataFrame", df[cols])


def style_movement_log(df: pd.DataFrame) -> Styler:
    """Format movement log with colour-coded movement types and monthly subtotals.

    Args:
        df: DataFrame from :func:`movement_log`.
    """
    type_order = {"new": 0, "expansion": 1, "reactivation": 2, "contraction": 3, "churn": 4}

    # Build display rows with subtotal rows inserted after each month
    rows: list[dict[str, str]] = []
    subtotal_indices: list[int] = []

    for month, grp in df.groupby("month", sort=True):
        month_str = str(month)
        for _, r in grp.iterrows():
            rows.append(
                {
                    "month": month_str,
                    "date": r["date"],
                    "customer": r["customer_name"] or r["customer_id"],
                    "customer_id": r["customer_id"],
                    "movement": r["movement_type"],
                    "amount": f"${r['amount']:,.2f}",
                }
            )
        # Monthly subtotal
        totals = grp.groupby("movement_type")["amount"].sum()
        parts = []
        for mt in sorted(totals.index, key=lambda t: type_order.get(t, 5)):
            parts.append(f"{mt}: ${totals[mt]:,.2f}")
        net = grp["amount"].sum()
        subtotal_indices.append(len(rows))
        rows.append(
            {
                "month": month_str,
                "date": "",
                "customer": "",
                "customer_id": "",
                "movement": " | ".join(parts),
                "amount": f"${net:,.2f}",
            }
        )

    display = pd.DataFrame(rows)

    def _highlight_subtotals(row: pd.Series) -> list[str]:
        if row.name in subtotal_indices:
            return ["font-weight: bold; background-color: #F5F5F4; color: #1C1917"] * len(row)
        return [""] * len(row)

    def _color_movement(val: object) -> str:
        colors = {
            "new": f"color: {COLORS['new']}",
            "expansion": f"color: {COLORS['expansion']}",
            "reactivation": f"color: {COLORS['reactivation']}",
            "contraction": f"color: {COLORS['contraction']}",
            "churn": f"color: {COLORS['churn']}",
        }
        return colors.get(str(val), "")

    return (
        display.style.apply(_highlight_subtotals, axis=1)
        .map(_color_movement, subset=["movement"])
        .hide(axis="index")
    )


def quick_ratio(tm: TidemillClient, start: str, end: str) -> dict[str, Any]:
    """Compute the SaaS Quick Ratio from MRR movements.

    ``Quick Ratio = (new + expansion + reactivation) / |churn + contraction|``

    Measures growth efficiency: how much new MRR is added for every dollar
    lost.  >4 is considered excellent, 1 is break-even, <1 is shrinking.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.

    Returns:
        Dict with ``gains``, ``losses`` (both positive dollars),
        ``quick_ratio`` (float or None when losses are zero), and the
        individual movement components.
    """
    df = breakdown(tm, start, end)
    amounts = df.set_index("movement_type")["amount"].to_dict()
    gain_parts = {
        "new": amounts.get("new", 0.0),
        "expansion": amounts.get("expansion", 0.0),
        "reactivation": amounts.get("reactivation", 0.0),
    }
    loss_parts = {
        "churn": abs(amounts.get("churn", 0.0)),
        "contraction": abs(amounts.get("contraction", 0.0)),
    }
    gains = sum(gain_parts.values())
    losses = sum(loss_parts.values())
    return {
        **gain_parts,
        **loss_parts,
        "gains": gains,
        "losses": losses,
        "quick_ratio": gains / losses if losses else None,
    }


def style_quick_ratio(data: dict[str, Any]) -> Styler:
    """Format Quick Ratio as a styled one-row summary.

    Args:
        data: Dict from :func:`quick_ratio`.
    """
    df = pd.DataFrame(
        [
            {
                "New": data["new"],
                "Expansion": data["expansion"],
                "Reactivation": data["reactivation"],
                "Gains": data["gains"],
                "Churn": data["churn"],
                "Contraction": data["contraction"],
                "Losses": data["losses"],
                "Quick Ratio": data["quick_ratio"],
            }
        ]
    )
    money = ["New", "Expansion", "Reactivation", "Gains", "Churn", "Contraction", "Losses"]
    styler = cast(
        "Styler",
        df.style.format(
            {
                **{c: "${:,.2f}" for c in money},
                "Quick Ratio": lambda v: f"{v:.2f}" if v is not None else "N/A",
            }
        ),
    )
    return styler.hide(axis="index")


def trend(tm: TidemillClient, start: str, end: str, interval: str = "month") -> pd.DataFrame:
    """Fetch ending MRR per period.

    Args:
        tm: Tidemill API client.
        start: ISO date string for period start.
        end: ISO date string for period end.
        interval: Bucket size — ``day``, ``week``, ``month``, ``quarter``,
            or ``year``.

    Returns:
        DataFrame with ``period`` and ``ending_mrr`` (dollars).
    """
    raw = tm.mrr_waterfall(start, end, interval=interval)
    df = pd.DataFrame(raw)
    df["ending_mrr"] = df["ending_mrr"] / 100
    df["period"] = pd.to_datetime(df["period"])
    df.attrs["interval"] = interval
    return df


# ── style ────────────────────────────────────────────────────────────


def style_snapshot(data: dict[str, Any]) -> Styler:
    """Format MRR/ARR snapshot as a styled table.

    Args:
        data: Dict from :func:`snapshot`.
    """
    df = pd.DataFrame([{"MRR": data["mrr"], "ARR": data["arr"]}])
    styler = cast("Styler", df.style.format("${:,.2f}"))
    return styler.hide(axis="index")


def style_waterfall(df: pd.DataFrame) -> Styler:
    """Format waterfall DataFrame as a styled table.

    Args:
        df: DataFrame from :func:`waterfall`.
    """
    display_cols = [
        "starting_mrr",
        "new",
        "expansion",
        "reactivation",
        "contraction",
        "churn",
        "net_change",
        "ending_mrr",
    ]
    interval = df.attrs.get("interval", "month")
    display = df.copy()
    display["period"] = format_periods(display["period"], interval)
    styled = display.set_index("period")[display_cols]
    return cast("Styler", styled.style.format("${:,.2f}"))


# ── charts ───────────────────────────────────────────────────────────


def plot_breakdown(df: pd.DataFrame) -> go.Figure:
    """Bar chart of MRR movements.

    Args:
        df: DataFrame from :func:`breakdown`.
    """
    fig = go.Figure(
        go.Bar(
            x=df.movement_type,
            y=df.amount,
            marker_color=[COLORS.get(t, COLORS["grey"]) for t in df.movement_type],
            text=[f"${v:,.0f}" for v in df.amount],
            textposition="outside",
        )
    )
    fig.update_layout(
        title="MRR Movements",
        yaxis_title="Amount ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",",
    )
    return fig


def plot_waterfall(df: pd.DataFrame) -> go.Figure:
    """MRR waterfall stacked bar + ending MRR line, per period.

    Args:
        df: DataFrame from :func:`waterfall`.
    """
    interval = df.attrs.get("interval", "month")
    dm = df.set_index("period")
    x = dm.index

    fig = go.Figure()
    fig.add_trace(
        go.Bar(name="Starting MRR", x=x, y=dm.starting_mrr, marker_color=COLORS["starting_mrr"])
    )
    for col in ["new", "expansion", "reactivation"]:
        if dm[col].any():
            fig.add_trace(go.Bar(name=col.title(), x=x, y=dm[col], marker_color=COLORS[col]))
    for col in ["contraction", "churn"]:
        if dm[col].any():
            fig.add_trace(go.Bar(name=col.title(), x=x, y=dm[col], marker_color=COLORS[col]))
    fig.add_trace(
        go.Scatter(
            name="Ending MRR",
            x=x,
            y=dm.ending_mrr,
            mode="lines+markers+text",
            line={"color": "black", "width": 2},
            marker={"size": 8},
            text=[f"${v:,.0f}" for v in dm.ending_mrr],
            textposition="top center",
        )
    )
    fig.update_layout(
        barmode="relative",
        title="MRR Waterfall",
        yaxis_title="MRR ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",",
        legend={"orientation": "h", "y": -0.15},
        height=500,
    )
    apply_period_xaxis(fig, x, interval)
    return fig


def plot_trend(df: pd.DataFrame) -> go.Figure:
    """MRR trend line over time.

    Args:
        df: DataFrame from :func:`trend`.
    """
    interval = df.attrs.get("interval", "month")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df.period,
            y=df.ending_mrr,
            mode="lines+markers+text",
            fill="tozeroy",
            line={"color": COLORS["new"], "width": 2.5},
            marker={"size": 8},
            text=[f"${v:,.0f}" for v in df.ending_mrr],
            textposition="top center",
        )
    )
    fig.update_layout(
        title="MRR Over Time",
        yaxis_title="MRR ($)",
        yaxis_tickprefix="$",
        yaxis_tickformat=",",
        yaxis_rangemode="tozero",
    )
    apply_period_xaxis(fig, df.period, interval)
    return fig
