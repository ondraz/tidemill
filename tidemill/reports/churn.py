"""Churn reports — data, style, and plotly chart functions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd
import plotly.graph_objects as go

from tidemill.reports._style import COLORS

if TYPE_CHECKING:
    from tidemill.reports.stripecheck.stripe_data import StripeData
    from tidemill.reports.stripecheck.tidemill_client import TidemillClient


# ── data ─────────────────────────────────────────────────────────────


def stripe_overview(
    tm: TidemillClient,
    sd: StripeData,
    start: str,
    end: str,
) -> dict[str, Any]:
    """Fetch churn comparison between Tidemill and Stripe.

    Args:
        tm: Tidemill API client.
        sd: Stripe data source.
        start: ISO date string for churn window start.
        end: ISO date string for churn window end.

    Returns:
        Dict with ``tidemill``/``stripe`` sub-dicts, match booleans,
        and ``active_mrr_cents``.
    """
    from tidemill.reports.stripecheck.compare import churn as compare_churn

    result = compare_churn(tm, sd, start, end)
    result["active_mrr_cents"] = int(sd.active.mrr_cents.sum())
    return result


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


def style_stripe_overview(data: dict[str, Any]) -> pd.io.formats.style.Styler:
    """Format churn overview as a styled comparison table.

    Args:
        data: Dict from :func:`stripe_overview`.
    """
    tm = data["tidemill"]
    st = data["stripe"]
    rows = []
    if tm["logo_churn"] is not None and st["logo_churn"] is not None:
        rows.append(
            {
                "Metric": "Logo churn",
                "Tidemill": tm["logo_churn"],
                "Stripe": st["logo_churn"],
                "Match": data["logo_match"],
            }
        )
    if tm["revenue_churn"] is not None and st["revenue_churn"] is not None:
        rows.append(
            {
                "Metric": "Revenue churn",
                "Tidemill": tm["revenue_churn"],
                "Stripe": st["revenue_churn"],
                "Match": data["revenue_match"],
            }
        )
    rows.append(
        {
            "Metric": "Active at start",
            "Tidemill": st["active_at_start"],
            "Stripe": st["active_at_start"],
            "Match": True,
        }
    )
    rows.append(
        {
            "Metric": "Fully churned",
            "Tidemill": st["fully_churned"],
            "Stripe": st["fully_churned"],
            "Match": True,
        }
    )
    df = pd.DataFrame(rows)

    def _fmt(v: object) -> str:
        if isinstance(v, float) and v < 1:
            return f"{v:.1%}"
        if isinstance(v, (int, float)):
            return f"{int(v):,d}"
        return str(v)

    return df.style.format({"Tidemill": _fmt, "Stripe": _fmt}).hide(axis="index")


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


# ── charts ───────────────────────────────────────────────────────────


def plot_stripe_overview(data: dict[str, Any]) -> go.Figure:
    """Customer-churn pie + revenue-impact bar from overview data.

    Args:
        data: Dict returned by :func:`stripe_overview`.
    """
    from plotly.subplots import make_subplots

    st = data["stripe"]
    n_retained = st["active_at_start"] - st["fully_churned"]
    n_churned = st["fully_churned"]
    active_mrr = data["active_mrr_cents"] / 100
    churned_mrr = st["churned_mrr_cents"] / 100

    fig = make_subplots(
        rows=1,
        cols=2,
        specs=[[{"type": "domain"}, {"type": "xy"}]],
        subplot_titles=[
            f"Logo Churn: {n_churned}/{st['active_at_start']} customers",
            "Revenue Impact of Churn",
        ],
    )
    fig.add_trace(
        go.Pie(
            labels=["Retained", "Fully churned"],
            values=[n_retained, n_churned],
            marker_colors=[COLORS["active"], COLORS["churn"]],
            pull=[0, 0.05],
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Bar(
            x=["Active MRR", "Churned MRR"],
            y=[active_mrr, churned_mrr],
            marker_color=[COLORS["active"], COLORS["churn"]],
            text=[f"${active_mrr:,.0f}", f"${churned_mrr:,.0f}"],
            textposition="outside",
            showlegend=False,
        ),
        row=1,
        col=2,
    )
    fig.update_yaxes(title_text="MRR ($)", tickprefix="$", tickformat=",", row=1, col=2)
    fig.update_layout(height=450)
    return fig


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


def stripe_customer_detail(
    sd: StripeData,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Per-customer Stripe churn detail for the measurement window.

    For each customer who was active at period start, shows their
    subscription count, churned MRR, and whether they fully churned.

    Args:
        sd: Stripe data source.
        start: ISO date string for window start.
        end: ISO date string for window end.

    Returns:
        DataFrame with one row per active-at-start customer.
    """
    from datetime import UTC

    subs = sd.subscriptions
    start_dt = pd.Timestamp(start, tz=UTC)
    end_dt = pd.Timestamp(end, tz=UTC)

    rows: list[dict[str, Any]] = []
    for cust, grp in subs.groupby("customer"):
        active_at_start = grp[
            (grp.created_at < start_dt)
            & ((grp.canceled_at.isna()) | (grp.canceled_at >= start_dt))
        ]
        if len(active_at_start) == 0:
            continue

        still_active = grp[
            (grp.created_at < end_dt) & ((grp.canceled_at.isna()) | (grp.canceled_at >= end_dt))
        ]
        canceled_in_period = grp[
            grp.canceled_at.notna() & (grp.canceled_at >= start_dt) & (grp.canceled_at < end_dt)
        ]
        churned_mrr = int(canceled_in_period.mrr_cents.sum())

        rows.append(
            {
                "customer": str(cust),
                "subs_at_start": len(active_at_start),
                "active_at_start": True,
                "fully_churned": len(still_active) == 0,
                "starting_mrr_cents": int(active_at_start.mrr_cents.sum()),
                "churned_mrr_cents": churned_mrr,
            }
        )

    return pd.DataFrame(rows).sort_values("customer").reset_index(drop=True)


def tidemill_customer_detail(
    tm: TidemillClient,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Per-customer Tidemill churn detail for the measurement window.

    Args:
        tm: Tidemill API client.
        start: ISO date string for window start.
        end: ISO date string for window end.

    Returns:
        DataFrame with one row per active-at-start customer.
    """
    data = tm.churn_customers(start, end)
    if not data:
        cols = ["customer", "active_at_start", "fully_churned", "churned_mrr_cents"]
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(data).rename(columns={"customer_id": "customer"})
    return df.sort_values("customer").reset_index(drop=True)


def customer_churn_diff(
    stripe_df: pd.DataFrame,
    tm_df: pd.DataFrame,
) -> pd.DataFrame:
    """Merge per-customer Stripe and Tidemill churn detail, flagging differences.

    Args:
        stripe_df: DataFrame from :func:`stripe_customer_detail`.
        tm_df: DataFrame from :func:`tidemill_customer_detail`.

    Returns:
        Merged DataFrame with columns from both sides plus a ``notes``
        column explaining any discrepancies.
    """
    s = stripe_df[["customer", "fully_churned", "starting_mrr_cents", "churned_mrr_cents"]].rename(
        columns={
            "fully_churned": "s_fully_churned",
            "starting_mrr_cents": "s_starting_mrr",
            "churned_mrr_cents": "s_churned_mrr",
        }
    )
    t = tm_df[["customer", "fully_churned", "starting_mrr_cents", "churned_mrr_cents"]].rename(
        columns={
            "fully_churned": "t_fully_churned",
            "starting_mrr_cents": "t_starting_mrr",
            "churned_mrr_cents": "t_churned_mrr",
        }
    )
    merged = s.merge(t, on="customer", how="outer", indicator=True)

    def _note(row: pd.Series) -> str:
        parts: list[str] = []
        if row["_merge"] == "left_only":
            return "Stripe only"
        if row["_merge"] == "right_only":
            return "Tidemill only"
        if row.get("s_fully_churned") != row.get("t_fully_churned"):
            parts.append(
                f"logo: S={'Y' if row['s_fully_churned'] else 'N'}"
                f" T={'Y' if row['t_fully_churned'] else 'N'}"
            )
        s_mrr = int(row.get("s_starting_mrr", 0) or 0)
        t_mrr = int(row.get("t_starting_mrr", 0) or 0)
        if s_mrr != t_mrr:
            parts.append(f"start MRR: ${s_mrr / 100:,.0f} vs ${t_mrr / 100:,.0f}")
        s_ch = int(row.get("s_churned_mrr", 0) or 0)
        t_ch = int(row.get("t_churned_mrr", 0) or 0)
        if s_ch != t_ch:
            parts.append(f"churned: ${s_ch / 100:,.0f} vs ${t_ch / 100:,.0f}")
        return "; ".join(parts) if parts else ""

    merged["notes"] = merged.apply(_note, axis=1)
    merged = merged.drop(columns=["_merge"])
    return merged.sort_values("customer").reset_index(drop=True)


def style_customer_detail(df: pd.DataFrame, label: str) -> pd.io.formats.style.Styler:
    """Format per-customer churn detail as a styled table with totals.

    Args:
        df: DataFrame from :func:`stripe_customer_detail` or
            :func:`tidemill_customer_detail`.
        label: Source label (``"Stripe"`` or ``"Tidemill"``).
    """
    display = df.copy()
    n_active = int(display.active_at_start.sum())
    n_churned = int(display.fully_churned.sum())
    total_starting = int(display.starting_mrr_cents.sum())
    total_churned = int(display.churned_mrr_cents.sum())

    display["starting_mrr"] = display.starting_mrr_cents.apply(lambda c: f"${c / 100:,.2f}")
    display["churned_mrr"] = display.churned_mrr_cents.apply(lambda c: f"${c / 100:,.2f}")

    # Totals row
    rate = total_churned / total_starting if total_starting else 0
    totals = pd.DataFrame(
        [
            {
                "customer": "TOTAL",
                "active_at_start": n_active,
                "fully_churned": n_churned,
                "starting_mrr": f"${total_starting / 100:,.2f}",
                "churned_mrr": f"${total_churned / 100:,.2f}",
                "subs_at_start": "",
            }
        ]
    )
    display = pd.concat([display, totals], ignore_index=True)

    cols = ["customer", "active_at_start", "fully_churned"]
    if "subs_at_start" in df.columns:
        cols.append("subs_at_start")
    cols += ["starting_mrr", "churned_mrr"]

    caption = f"{label}: revenue churn = {rate:.1%}"
    return display[cols].style.set_caption(caption).hide(axis="index")


def style_customer_churn_diff(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """Format the merged diff table with row highlights for mismatches.

    Args:
        df: DataFrame from :func:`customer_churn_diff`.
    """

    def _dollars(col: str) -> pd.Series:
        return df[col].fillna(0).apply(lambda c: f"${c / 100:,.2f}")

    display = df.copy()
    display["s_starting_mrr"] = _dollars("s_starting_mrr")
    display["t_starting_mrr"] = _dollars("t_starting_mrr")
    display["s_churned_mrr"] = _dollars("s_churned_mrr")
    display["t_churned_mrr"] = _dollars("t_churned_mrr")

    # Totals row
    s_start = int(df.s_starting_mrr.fillna(0).sum())
    t_start = int(df.t_starting_mrr.fillna(0).sum())
    s_churn = int(df.s_churned_mrr.fillna(0).sum())
    t_churn = int(df.t_churned_mrr.fillna(0).sum())
    s_rate = s_churn / s_start if s_start else 0
    t_rate = t_churn / t_start if t_start else 0
    totals = pd.DataFrame(
        [
            {
                "customer": "TOTAL",
                "s_fully_churned": int(df.s_fully_churned.fillna(False).sum()),
                "t_fully_churned": int(df.t_fully_churned.fillna(False).sum()),
                "s_starting_mrr": f"${s_start / 100:,.2f}",
                "t_starting_mrr": f"${t_start / 100:,.2f}",
                "s_churned_mrr": f"${s_churn / 100:,.2f}",
                "t_churned_mrr": f"${t_churn / 100:,.2f}",
                "notes": f"rate: S={s_rate:.1%} T={t_rate:.1%}",
            }
        ]
    )
    display = pd.concat([display, totals], ignore_index=True)

    cols = [
        "customer",
        "s_fully_churned",
        "t_fully_churned",
        "s_starting_mrr",
        "t_starting_mrr",
        "s_churned_mrr",
        "t_churned_mrr",
        "notes",
    ]

    def _highlight(row: pd.Series) -> list[str]:
        if row["notes"]:
            return ["background-color: #FEF3C7"] * len(row)
        return [""] * len(row)

    return (
        display[cols]
        .style.apply(_highlight, axis=1)
        .set_caption("Per-customer churn: Stripe vs Tidemill")
        .hide(axis="index")
    )


def stripe_cancellations(
    sd: StripeData,
    start: str,
    end: str,
) -> pd.DataFrame:
    """Subscriptions canceled within the measurement window.

    Args:
        sd: Stripe data source.
        start: ISO date string for window start.
        end: ISO date string for window end.

    Returns:
        DataFrame with canceled subscription details, sorted by date.
    """
    from datetime import UTC

    subs = sd.subscriptions
    start_dt = pd.Timestamp(start, tz=UTC)
    end_dt = pd.Timestamp(end, tz=UTC)
    mask = subs.canceled_at.notna() & (subs.canceled_at >= start_dt) & (subs.canceled_at < end_dt)
    df = subs.loc[mask, ["id", "customer", "mrr_cents", "canceled_at"]].copy()
    df["canceled_month"] = df.canceled_at.dt.strftime("%Y-%m")
    df["mrr"] = df.mrr_cents.apply(lambda c: f"${c / 100:,.2f}")
    return df.sort_values("canceled_at").reset_index(drop=True)


def style_stripe_cancellations(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    """Format canceled subscriptions as a styled table.

    Args:
        df: DataFrame from :func:`stripe_cancellations`.
    """
    return df[["id", "customer", "canceled_month", "mrr"]].style.hide(axis="index")


def plot_stripe_detail(stripe_churn: dict[str, Any]) -> go.Figure:
    """Stacked retention bars from Stripe churn data.

    Shows retained vs churned customers (left) and MRR (right).

    Args:
        stripe_churn: Dict returned by
            ``stripecheck.stripe_metrics.churn_rates``.
    """
    from plotly.subplots import make_subplots

    n_start = stripe_churn["active_at_start"]
    n_churned = stripe_churn["fully_churned"]
    n_retained = n_start - n_churned
    starting_mrr = stripe_churn["starting_mrr_cents"] / 100
    churned_mrr = stripe_churn["churned_mrr_cents"] / 100
    retained_mrr = starting_mrr - churned_mrr

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=[
            f"Customers ({n_start} at start)",
            f"MRR (${starting_mrr:,.0f} starting)",
        ],
    )
    for col, retained, churned, fmt in [
        (1, n_retained, n_churned, "d"),
        (2, retained_mrr, churned_mrr, ",.0f"),
    ]:
        prefix = "$" if col == 2 else ""
        fig.add_trace(
            go.Bar(
                x=[""],
                y=[retained],
                name="Retained",
                marker_color=COLORS["active"],
                showlegend=(col == 1),
                text=[f"{prefix}{retained:{fmt}}"],
                textposition="inside",
            ),
            row=1,
            col=col,
        )
        fig.add_trace(
            go.Bar(
                x=[""],
                y=[churned],
                name="Churned",
                marker_color=COLORS["churn"],
                showlegend=(col == 1),
                text=[f"{prefix}{churned:{fmt}}"],
                textposition="inside",
            ),
            row=1,
            col=col,
        )
    fig.update_layout(barmode="stack", height=400)
    fig.update_yaxes(title_text="Count", row=1, col=1)
    fig.update_yaxes(title_text="MRR ($)", tickprefix="$", tickformat=",", row=1, col=2)
    return fig
