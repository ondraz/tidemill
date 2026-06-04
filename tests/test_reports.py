"""Tests for source-grouping in the reports library.

All database-free — they exercise the styling helpers, the per-source chart
builders, and the client's source-filter plumbing with synthetic frames.
"""

from __future__ import annotations

import pandas as pd

from tidemill.reports import churn, ltv, mrr, retention, trials, usage_revenue
from tidemill.reports._style import (
    SOURCE_COLORS,
    iter_sources,
    plot_grouped_bars,
    plot_grouped_lines,
    source_color,
    source_label,
)
from tidemill.reports.client import TidemillClient

# ── Styling helpers ──────────────────────────────────────────────────────


class TestSourceStyleHelpers:
    def test_source_label_known_and_slug(self):
        assert source_label("stripe") == "Stripe"
        assert source_label("chargebee") == "Chargebee"
        assert source_label("killbill") == "Kill Bill"
        assert source_label("acme_billing") == "Acme Billing"

    def test_source_label_missing(self):
        assert source_label(None) == "Unknown"
        assert source_label("") == "Unknown"
        assert source_label(float("nan")) == "Unknown"

    def test_source_color_brand_then_fallback(self):
        assert source_color("stripe") == SOURCE_COLORS["stripe"]
        # Unknown source falls back to the colour cycle (deterministic by index).
        c0 = source_color("mystery", 0)
        c1 = source_color("mystery", 1)
        assert c0 != c1

    def test_iter_sources_orders_known_first(self):
        df = pd.DataFrame(
            {
                "source": ["chargebee", "zzz_other", "stripe"],
                "v": [1, 2, 3],
            }
        )
        order = [s for s, _ in iter_sources(df)]
        # Palette order: stripe before chargebee; unknown sources come last.
        assert order == ["stripe", "chargebee", "zzz_other"]

    def test_iter_sources_no_column_yields_whole_frame(self):
        df = pd.DataFrame({"v": [1, 2]})
        pairs = list(iter_sources(df))
        assert len(pairs) == 1
        assert pairs[0][0] is None


# ── Generic grouped chart builders ───────────────────────────────────────


class TestGroupedBuilders:
    def _grouped_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "period": pd.to_datetime(["2025-01-01", "2025-01-01", "2025-02-01"]),
                "value": [10, 5, 12],
                "source": ["stripe", "chargebee", "stripe"],
            }
        )

    def test_grouped_lines_one_trace_per_source(self):
        fig = plot_grouped_lines(
            self._grouped_frame(),
            x_col="period",
            y_col="value",
            title="t",
            yaxis_title="y",
        )
        assert {tr.name for tr in fig.data} == {"Stripe", "Chargebee"}

    def test_grouped_bars_one_trace_per_source(self):
        fig = plot_grouped_bars(
            self._grouped_frame(),
            x_col="period",
            y_col="value",
            title="t",
            yaxis_title="y",
        )
        assert len(fig.data) == 2
        assert fig.layout.barmode == "group"


# ── Per-report grouped charts ────────────────────────────────────────────


def _two_source(**cols: list) -> pd.DataFrame:
    df = pd.DataFrame({"source": ["stripe", "chargebee"], **cols})
    df.attrs["interval"] = "month"
    return df


class TestReportChartsGroup:
    def test_mrr_trend(self):
        df = _two_source(
            period=pd.to_datetime(["2025-01-01", "2025-01-01"]),
            ending_mrr=[100.0, 50.0],
        )
        assert len(mrr.plot_trend(df).data) == 2

    def test_mrr_breakdown_categorical(self):
        df = pd.DataFrame(
            {
                "movement_type": ["new", "new"],
                "amount": [10.0, 4.0],
                "amount_base": [1000, 400],
                "source": ["stripe", "chargebee"],
            }
        )
        fig = mrr.plot_breakdown(df)
        assert len(fig.data) == 2

    def test_usage_series(self):
        df = _two_source(
            period=pd.to_datetime(["2025-01-01", "2025-01-01"]),
            revenue=[10.0, 5.0],
        )
        assert len(usage_revenue.plot_series(df).data) == 2

    def test_trials_timeline(self):
        df = _two_source(
            period=["2025-01-01", "2025-01-01"],
            started=[10, 4],
            converted=[5, 1],
            expired=[2, 1],
            conversion_rate=[0.5, 0.25],
        )
        assert len(trials.plot_timeline(df).data) == 2

    def test_churn_timeline(self):
        df = _two_source(
            month=pd.to_datetime(["2025-01-01", "2025-01-01"]),
            logo_churn=[0.05, 0.1],
            revenue_churn=[0.03, 0.08],
        )
        assert len(churn.plot_timeline(df).data) == 2

    def test_churn_lost_mrr(self):
        df = _two_source(
            period=pd.to_datetime(["2025-01-01", "2025-01-01"]),
            churn_dollars=[100.0, 50.0],
        )
        assert len(churn.plot_monthly_lost_mrr(df).data) == 2

    def test_ltv_arpu_timeline(self):
        df = _two_source(
            month=pd.to_datetime(["2025-01-01", "2025-01-01"]),
            active_customers=[10, 5],
            mrr_dollars=[1000.0, 500.0],
            arpu_dollars=[100.0, 100.0],
        )
        assert len(ltv.plot_arpu_timeline(df).data) == 2

    def test_retention_nrr_grr(self):
        df = _two_source(
            month=pd.to_datetime(["2025-01-01", "2025-01-01"]),
            nrr=[1.05, 0.95],
            grr=[0.9, 0.85],
        )
        # One NRR line per source (the 100% reference hline is a shape, not a trace).
        assert len(retention.plot_nrr_grr(df).data) == 2

    def test_single_source_unchanged(self):
        """Without a ``source`` column the charts keep their single-trace form."""
        df = pd.DataFrame(
            {"period": pd.to_datetime(["2025-01-01", "2025-02-01"]), "ending_mrr": [100.0, 120.0]}
        )
        df.attrs["interval"] = "month"
        assert len(mrr.plot_trend(df).data) == 1


# ── Client source filtering ──────────────────────────────────────────────


class TestClientSourceFilter:
    def test_source_filter_param(self):
        assert TidemillClient._source_filter("stripe") == {"filter": "source=stripe"}
        assert TidemillClient._source_filter(None) == {}

    def test_source_types_dedups_and_sorts(self, monkeypatch):
        tm = TidemillClient(base_url="http://x")
        monkeypatch.setattr(
            tm,
            "sources",
            lambda: [
                {"type": "stripe"},
                {"type": "chargebee"},
                {"type": "stripe"},
                {"name": "no-type"},
            ],
        )
        assert tm.source_types() == ["chargebee", "stripe"]

    def test_mrr_passes_source_filter(self, monkeypatch):
        tm = TidemillClient(base_url="http://x")
        captured: dict = {}

        def fake_get(path, **params):
            captured["path"] = path
            captured["params"] = params
            return 4200

        monkeypatch.setattr(tm, "get", fake_get)
        assert tm.mrr(at="2025-06-01", source="chargebee") == 4200
        assert captured["params"]["filter"] == "source=chargebee"
        assert captured["params"]["at"] == "2025-06-01"
