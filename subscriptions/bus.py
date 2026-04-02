"""Kafka event bus — producer and consumer wrappers around aiokafka."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from subscriptions.events import Event, from_json, to_json

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

DEFAULT_TOPIC = "subscriptions.events"
DLQ_TOPIC = "subscriptions.events.dlq"


class EventProducer:
    """Publishes events to Kafka, keyed by ``customer_id``."""

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str = DEFAULT_TOPIC,
    ) -> None:
        self._topic = topic
        self._producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)

    async def start(self) -> None:
        await self._producer.start()

    async def stop(self) -> None:
        await self._producer.stop()

    async def publish(self, event: Event) -> None:
        await self._producer.send_and_wait(
            self._topic,
            value=to_json(event),
            key=event.customer_id.encode(),
        )

    async def publish_many(self, events: list[Event]) -> None:
        for event in events:
            await self._producer.send(
                self._topic,
                value=to_json(event),
                key=event.customer_id.encode(),
            )
        await self._producer.flush()


class EventConsumer:
    """Consumes events from Kafka, yielding deserialized ``Event`` objects."""

    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        topic: str = DEFAULT_TOPIC,
        **kwargs: Any,
    ) -> None:
        self._consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=False,
            **kwargs,
        )

    async def start(self) -> None:
        await self._consumer.start()

    async def stop(self) -> None:
        await self._consumer.stop()

    async def __aiter__(self) -> AsyncIterator[Event]:
        async for msg in self._consumer:
            yield from_json(msg.value)

    async def commit(self) -> None:
        await self._consumer.commit()
