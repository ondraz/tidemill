"""Worker process — multiple Kafka consumer tasks running concurrently."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import TYPE_CHECKING

from subscriptions.bus import DLQ_TOPIC, EventConsumer, EventProducer
from subscriptions.database import make_engine, make_session_factory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from subscriptions.events import Event

logger = logging.getLogger(__name__)


async def run_worker() -> None:
    db_url = os.environ.get(
        "SUBSCRIPTIONS_DATABASE_URL",
        "postgresql+asyncpg://localhost/subscriptions",
    )
    kafka_url = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    engine = make_engine(db_url)
    factory = make_session_factory(engine)

    dlq = EventProducer(bootstrap_servers=kafka_url, topic=DLQ_TOPIC)
    await dlq.start()

    stop = asyncio.Event()

    def _signal_handler() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    tasks = [
        asyncio.create_task(
            _consume_state(kafka_url, factory, dlq, stop),
            name="state",
        ),
        asyncio.create_task(
            _consume_metric(
                kafka_url,
                "subscriptions.metric.mrr",
                "mrr",
                factory,
                dlq,
                stop,
            ),
            name="metric.mrr",
        ),
        asyncio.create_task(
            _consume_metric(
                kafka_url,
                "subscriptions.metric.churn",
                "churn",
                factory,
                dlq,
                stop,
            ),
            name="metric.churn",
        ),
        asyncio.create_task(
            _consume_metric(
                kafka_url,
                "subscriptions.metric.retention",
                "retention",
                factory,
                dlq,
                stop,
            ),
            name="metric.retention",
        ),
    ]

    logger.info("Worker started with %d consumer tasks", len(tasks))
    await stop.wait()
    logger.info("Shutting down worker …")

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    await dlq.stop()
    await engine.dispose()
    logger.info("Worker stopped.")


# ── consumer loops ───────────────────────────────────────────────────────


async def _consume_state(
    kafka_url: str,
    factory: async_sessionmaker[AsyncSession],
    dlq: EventProducer,
    stop: asyncio.Event,
) -> None:
    from subscriptions.state import handle_state_event

    consumer = EventConsumer(
        bootstrap_servers=kafka_url,
        group_id="subscriptions.state",
    )
    await consumer.start()
    try:
        async for event in consumer:
            if stop.is_set():
                break
            try:
                async with factory() as session:
                    await handle_state_event(session, event)
                    await session.commit()
                await consumer.commit()
            except Exception:
                logger.exception("State consumer error for event %s", event.id)
                await _send_to_dlq(dlq, event)
    finally:
        await consumer.stop()


async def _consume_metric(
    kafka_url: str,
    group_id: str,
    metric_name: str,
    factory: async_sessionmaker[AsyncSession],
    dlq: EventProducer,
    stop: asyncio.Event,
) -> None:
    from subscriptions.metrics.registry import discover_metrics

    metrics = {m.name: m for m in discover_metrics()}
    metric = metrics[metric_name]

    consumer = EventConsumer(
        bootstrap_servers=kafka_url,
        group_id=group_id,
    )
    await consumer.start()
    try:
        async for event in consumer:
            if stop.is_set():
                break
            if event.type not in metric.event_types:
                await consumer.commit()
                continue
            try:
                async with factory() as session:
                    metric.init(db=session)
                    await metric.handle_event(event)
                    await session.commit()
                await consumer.commit()
            except Exception:
                logger.exception("Metric %s consumer error for event %s", metric_name, event.id)
                await _send_to_dlq(dlq, event)
    finally:
        await consumer.stop()


async def _send_to_dlq(dlq: EventProducer, event: Event) -> None:
    try:
        await dlq.publish(event)
    except Exception:
        logger.exception("Failed to send event %s to DLQ", event.id)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
