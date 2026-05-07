"""Tidemill REST API client for notebook comparisons.

Wraps every metric endpoint with typed convenience methods so notebooks
can fetch Tidemill results in one line.  Environment variables:

- ``TIDEMILL_API``     — base URL (default ``http://localhost:8000``)
- ``TIDEMILL_API_KEY`` — bearer token (optional, omit if auth is disabled)
"""

from __future__ import annotations

import os
from typing import Any, cast

import requests


class TidemillClient:
    """Thin wrapper around the Tidemill REST API.

    Args:
        base_url: Override for the API base URL.  Falls back to the
            ``TIDEMILL_API`` env var, then ``http://localhost:8000``.
        api_key: Bearer token.  Falls back to ``TIDEMILL_API_KEY``.
        verify_ssl: Passed through to ``requests``.  Defaults to
            ``False`` for local dev.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        verify_ssl: bool = False,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("TIDEMILL_API", "http://localhost:8000")
        ).rstrip("/")
        self._session = requests.Session()
        self._session.verify = verify_ssl

        key = api_key or os.environ.get("TIDEMILL_API_KEY", "")
        if key:
            self._session.headers["Authorization"] = f"Bearer {key}"

    # ── generic request ──────────────────────────────────────────────

    def get(self, path: str, **params: Any) -> Any:
        """GET ``path`` with query ``params``, return parsed JSON."""
        r = self._session.get(f"{self.base_url}{path}", params=params)
        r.raise_for_status()
        return r.json()

    # ── MRR ──────────────────────────────────────────────────────────

    def mrr(self, at: str | None = None) -> int:
        """Current MRR in cents.  ``at`` is an ISO date string."""
        kw: dict[str, str] = {}
        if at:
            kw["at"] = at
        return cast("int", self.get("/api/metrics/mrr", **kw))

    def arr(self, at: str | None = None) -> int:
        """Current ARR in cents (MRR x 12)."""
        kw: dict[str, str] = {}
        if at:
            kw["at"] = at
        return cast("int", self.get("/api/metrics/arr", **kw))

    def mrr_breakdown(self, start: str, end: str) -> list[dict[str, Any]]:
        """MRR movements (new / expansion / contraction / churn) for a period."""
        return cast(
            "list[dict[str, Any]]",
            self.get("/api/metrics/mrr/breakdown", start=start, end=end),
        )

    def mrr_waterfall(self, start: str, end: str, interval: str = "month") -> list[dict[str, Any]]:
        """MRR waterfall with starting/ending MRR and movements per period."""
        return cast(
            "list[dict[str, Any]]",
            self.get("/api/metrics/mrr/waterfall", start=start, end=end, interval=interval),
        )

    def mrr_components(self) -> dict[str, int]:
        """Current MRR split into ``subscription_mrr`` + ``usage_mrr`` (cents)."""
        return self.get("/api/metrics/mrr/components")

    # ── Usage revenue ────────────────────────────────────────────────

    def usage_revenue(self, start: str, end: str) -> int:
        """Total finalized usage revenue (cents) for the period."""
        return self.get("/api/metrics/usage-revenue", start=start, end=end)

    def usage_revenue_series(
        self,
        start: str,
        end: str,
        interval: str = "month",
    ) -> list[dict[str, Any]]:
        """Usage revenue per period (cents)."""
        return self.get(
            "/api/metrics/usage-revenue/series",
            start=start,
            end=end,
            interval=interval,
        )

    def usage_revenue_by_customer(self, start: str, end: str) -> list[dict[str, Any]]:
        """Per-customer usage revenue for the period (cents)."""
        return self.get("/api/metrics/usage-revenue/by-customer", start=start, end=end)

    # ── Churn ────────────────────────────────────────────────────────

    def churn(
        self,
        start: str,
        end: str,
        type: str = "logo",  # noqa: A002
    ) -> float | None:
        """Churn rate for the period.  ``type`` is ``"logo"`` or ``"revenue"``."""
        return cast(
            "float | None", self.get("/api/metrics/churn", start=start, end=end, type=type)
        )

    def churn_customers(self, start: str, end: str) -> list[dict[str, Any]]:
        """Per-customer churn detail for the period."""
        return cast(
            "list[dict[str, Any]]",
            self.get("/api/metrics/churn/customers", start=start, end=end),
        )

    def churn_revenue_events(self, start: str, end: str) -> list[dict[str, Any]]:
        """Individual revenue-churn events for active-at-start customers."""
        return cast(
            "list[dict[str, Any]]",
            self.get("/api/metrics/churn/revenue-events", start=start, end=end),
        )

    # ── Retention ────────────────────────────────────────────────────

    def retention(self, start: str, end: str, **kw: Any) -> Any:
        """Cohort retention data.  Pass ``query_type="nrr"`` or ``"grr"``."""
        return self.get("/api/metrics/retention", start=start, end=end, **kw)

    def cohort_matrix(self, start: str, end: str) -> list[dict[str, Any]]:
        """Cohort retention matrix — one row per (cohort_month, active_month)."""
        return cast(
            "list[dict[str, Any]]",
            self.get(
                "/api/metrics/retention",
                start=start,
                end=end,
                query_type="cohort_matrix",
            ),
        )

    # ── LTV ──────────────────────────────────────────────────────────

    def ltv(self, start: str, end: str) -> int | None:
        """Simple LTV = ARPU / monthly churn rate, in cents."""
        return cast("int | None", self.get("/api/metrics/ltv", start=start, end=end))

    def arpu(self, at: str | None = None) -> int | None:
        """Average Revenue Per User in cents."""
        kw: dict[str, str] = {}
        if at:
            kw["at"] = at
        return cast("int | None", self.get("/api/metrics/ltv/arpu", **kw))

    def cohort_ltv(self, start: str, end: str) -> list[dict[str, Any]]:
        """Per-cohort LTV breakdown."""
        return cast(
            "list[dict[str, Any]]", self.get("/api/metrics/ltv/cohort", start=start, end=end)
        )

    # ── Trials ───────────────────────────────────────────────────────

    def trial_rate(self, start: str, end: str) -> float | None:
        """Overall trial-to-paid conversion rate."""
        return cast("float | None", self.get("/api/metrics/trials", start=start, end=end))

    def trial_funnel(self, start: str, end: str) -> dict[str, Any]:
        """Trial funnel: started / converted / expired / conversion_rate."""
        return cast("dict[str, Any]", self.get("/api/metrics/trials/funnel", start=start, end=end))

    def trial_series(self, start: str, end: str, interval: str = "month") -> list[dict[str, Any]]:
        """Time-series of trial metrics per ``interval``."""
        return cast(
            "list[dict[str, Any]]",
            self.get("/api/metrics/trials/series", start=start, end=end, interval=interval),
        )

    # ── Sources ──────────────────────────────────────────────────────

    def sources(self) -> list[dict[str, Any]]:
        """Connected billing sources."""
        return cast("list[dict[str, Any]]", self.get("/api/sources"))
