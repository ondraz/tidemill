"""Tests for the canonical vocabulary helpers in tidemill.connectors.base.

These guard the contract every connector must satisfy: canonical enum
validation rejects non-canonical writes (DLQ'd by the worker), and
:func:`compute_mrr_cents` normalizes any plan interval onto monthly cents
identically for all connectors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from tidemill.connectors.base import (
    CANONICAL_LINE_ITEM_KINDS,
    CANONICAL_SUBSCRIPTION_STATUSES,
    CanonicalEnumViolation,
    WebhookConnector,
    compute_mrr_cents,
    validate_canonical,
)

if TYPE_CHECKING:
    from tidemill.events import Event


class TestValidateCanonical:
    def test_accepts_canonical_value(self):
        assert validate_canonical("active", CANONICAL_SUBSCRIPTION_STATUSES, "x") == "active"

    def test_passes_through_none(self):
        # Connectors that omit an optional canonical field are legal.
        assert validate_canonical(None, CANONICAL_SUBSCRIPTION_STATUSES, "x") is None

    def test_rejects_non_canonical(self):
        with pytest.raises(CanonicalEnumViolation) as excinfo:
            validate_canonical("zombie", CANONICAL_SUBSCRIPTION_STATUSES, "subscription.status")
        assert excinfo.value.field == "subscription.status"
        assert excinfo.value.value == "zombie"
        assert excinfo.value.allowed == CANONICAL_SUBSCRIPTION_STATUSES

    def test_violation_message_lists_allowed_values(self):
        with pytest.raises(CanonicalEnumViolation) as excinfo:
            validate_canonical("foo", CANONICAL_LINE_ITEM_KINDS, "line.kind")
        assert "line.kind" in str(excinfo.value)
        assert "foo" in str(excinfo.value)


class TestComputeMrrCents:
    def test_monthly_passthrough(self):
        assert compute_mrr_cents(7900, "month", 1, 1) == 7900

    def test_yearly_divides_by_twelve(self):
        # Annual $790 → ~$65.83/mo (floored).
        assert compute_mrr_cents(79000, "year", 1, 1) == 6583

    def test_quarterly_divides_by_interval_count(self):
        # interval=month, count=3 → divide by 3 (a quarter spans 3 months).
        assert compute_mrr_cents(9000, "month", 3, 1) == 3000

    def test_biannual(self):
        # interval=year, count=2 → divide by 24 months.
        assert compute_mrr_cents(120000, "year", 2, 1) == 5000

    def test_weekly_scales_by_52_over_12(self):
        assert compute_mrr_cents(1000, "week", 1, 1) == int(1000 * 52 / 12)

    def test_daily_scales_by_365_over_12(self):
        assert compute_mrr_cents(100, "day", 1, 1) == int(100 * 365 / 12)

    def test_quantity_multiplier(self):
        assert compute_mrr_cents(1000, "month", 1, 5) == 5000

    def test_zero_amount(self):
        assert compute_mrr_cents(0, "month", 1, 1) == 0

    def test_missing_interval(self):
        assert compute_mrr_cents(1000, None, 1, 1) == 0

    def test_unknown_interval_returns_zero(self):
        # The connector should have validated interval first; an unknown one
        # is treated as zero rather than raising, matching the policy on
        # other malformed inputs.
        assert compute_mrr_cents(1000, "fortnight", 1, 1) == 0

    def test_default_interval_count_and_quantity(self):
        assert compute_mrr_cents(2500, "month") == 2500


class TestVerifySignatureDefault:
    """A connector that forgets to override verify_signature must NOT silently accept.

    The base class raises so the gap surfaces during integration testing
    instead of becoming a silent auth bypass in production.
    """

    class _StubConnector(WebhookConnector):
        @property
        def source_type(self) -> str:
            return "stub"

        def translate(self, webhook_payload: dict[str, Any]) -> list[Event]:
            return []

    def test_default_raises_not_implemented(self):
        conn = self._StubConnector(source_id="stub", config={})
        with pytest.raises(NotImplementedError) as excinfo:
            conn.verify_signature(b"body", "sig")
        # Error message names the offending class so test output points
        # at the connector that forgot to override.
        assert "_StubConnector" in str(excinfo.value)
        assert "verify_signature" in str(excinfo.value)
