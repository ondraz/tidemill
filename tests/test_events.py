"""Tests for Event dataclass, serialization, and make_event_id."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from subscriptions.events import Event, from_json, make_event_id, to_json


class TestMakeEventId:
    def test_deterministic(self):
        """Same inputs always produce the same ID."""
        a = make_event_id("src_1", "subscription.created", "sub_123")
        b = make_event_id("src_1", "subscription.created", "sub_123")
        assert a == b

    def test_different_source(self):
        a = make_event_id("src_1", "subscription.created", "sub_123")
        b = make_event_id("src_2", "subscription.created", "sub_123")
        assert a != b

    def test_different_type(self):
        a = make_event_id("src_1", "subscription.created", "sub_123")
        b = make_event_id("src_1", "subscription.activated", "sub_123")
        assert a != b

    def test_different_external_id(self):
        a = make_event_id("src_1", "subscription.created", "sub_123")
        b = make_event_id("src_1", "subscription.created", "sub_456")
        assert a != b

    def test_returns_valid_uuid_string(self):
        import uuid

        result = make_event_id("s", "t", "e")
        uuid.UUID(result)  # raises if invalid


class TestEventSerialization:
    @pytest.fixture
    def sample_event(self) -> Event:
        return Event(
            id="evt-001",
            source_id="src_1",
            type="subscription.created",
            occurred_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
            published_at=datetime(2026, 1, 15, 12, 0, 1, tzinfo=UTC),
            customer_id="cus_abc",
            payload={"mrr_cents": 4999, "currency": "USD"},
        )

    def test_round_trip(self, sample_event: Event):
        data = to_json(sample_event)
        restored = from_json(data)
        assert restored.id == sample_event.id
        assert restored.source_id == sample_event.source_id
        assert restored.type == sample_event.type
        assert restored.occurred_at == sample_event.occurred_at
        assert restored.published_at == sample_event.published_at
        assert restored.customer_id == sample_event.customer_id
        assert restored.payload == sample_event.payload

    def test_to_json_returns_bytes(self, sample_event: Event):
        assert isinstance(to_json(sample_event), bytes)

    def test_payload_preserved(self, sample_event: Event):
        restored = from_json(to_json(sample_event))
        assert restored.payload["mrr_cents"] == 4999
        assert restored.payload["currency"] == "USD"

    def test_empty_payload_round_trip(self):
        e = Event(
            id="evt-002",
            source_id="src_1",
            type="customer.created",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            customer_id="cus_1",
            payload={},
        )
        assert from_json(to_json(e)).payload == {}


class TestEventDataclass:
    def test_frozen(self):
        e = Event(
            id="evt-001",
            source_id="src_1",
            type="test",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            customer_id="cus_1",
            payload={},
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            e.type = "mutated"  # type: ignore[misc]

    def test_equality(self):
        kwargs = dict(
            id="evt-001",
            source_id="src_1",
            type="test",
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
            customer_id="cus_1",
            payload={"x": 1},
        )
        assert Event(**kwargs) == Event(**kwargs)
