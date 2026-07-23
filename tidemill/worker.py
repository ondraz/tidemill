"""Worker process — multiple Kafka consumer tasks running concurrently."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import TYPE_CHECKING

from tidemill._logging import configure_logging
from tidemill.bus import DLQ_TOPIC, EventConsumer, EventProducer
from tidemill.database import make_engine, make_session_factory
from tidemill.otel import init_otel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from tidemill.events import Event

logger = logging.getLogger(__name__)

# SQLSTATE 42P01 — "undefined_table". Seen when the worker tries to bootstrap
# connector_source before the API process has created the schema on a cold DB.
_UNDEFINED_TABLE_SQLSTATE = "42P01"


def _is_missing_table(exc: Exception) -> bool:
    """True when *exc* is a Postgres "undefined table" error (SQLSTATE 42P01)."""
    sqlstate = getattr(getattr(exc, "orig", None), "sqlstate", None)
    if sqlstate == _UNDEFINED_TABLE_SQLSTATE:
        return True
    # asyncpg's DBAPI adapter doesn't always surface .sqlstate on .orig, so
    # fall back to the rendered message, which embeds "... does not exist".
    return "does not exist" in str(exc).lower()


async def _bootstrap_connector_sources(
    engine: AsyncEngine,
    *,
    attempts: int = 30,
    delay: float = 2.0,
) -> None:
    """Bootstrap connector_source rows, waiting out a not-yet-created schema.

    On a fresh database the API process owns schema creation (``create_all``
    in its lifespan); the worker can win the startup race and find
    ``connector_source`` missing. Rather than crash-loop on that race, retry
    until the table appears (up to ``attempts`` × ``delay`` seconds) before
    giving up. Any other error (or a persistently missing table) is re-raised.
    """
    from sqlalchemy.exc import ProgrammingError

    from tidemill.bootstrap import ensure_connector_sources

    for attempt in range(1, attempts + 1):
        try:
            async with engine.begin() as conn:
                await ensure_connector_sources(conn)
            return
        except ProgrammingError as exc:
            if not _is_missing_table(exc) or attempt == attempts:
                raise
            logger.warning(
                "connector_source not ready (attempt %d/%d) — waiting %.0fs for "
                "the API to create the schema",
                attempt,
                attempts,
                delay,
            )
            await asyncio.sleep(delay)


async def run_worker() -> None:
    init_otel("tidemill-worker")
    configure_logging("tidemill-worker")
    db_url = os.environ.get(
        "TIDEMILL_DATABASE_URL",
        "postgresql+asyncpg://localhost/tidemill",
    )
    kafka_url = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

    engine = make_engine(db_url)

    # Ensure a connector_source row exists for every configured connector
    # (TIDEMILL_CONNECTORS, e.g. "stripe,chargebee") before consuming events,
    # so the consumer never hits an FK violation when it persists an event.
    # The API process owns schema creation (create_all in its lifespan); on a
    # cold start the worker can win the race and find the table missing, so
    # this waits for the schema instead of crashing.
    await _bootstrap_connector_sources(engine)

    factory = make_session_factory(engine)

    dlq = EventProducer(bootstrap_servers=kafka_url, topic=DLQ_TOPIC)
    await dlq.start()

    stop = asyncio.Event()

    def _signal_handler() -> None:
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    from tidemill.fx_sync import run_periodic_fx_sync
    from tidemill.metrics.registry import discover_metrics

    # Pre-fill fx_rate so the first batch of events doesn't dead-letter
    # on FxRateMissingError before the periodic loop has a chance to run.
    tasks: list[asyncio.Task[None]] = [
        asyncio.create_task(
            run_periodic_fx_sync(factory, stop=stop),
            name="fx-sync",
        ),
        asyncio.create_task(
            _consume_state(kafka_url, factory, dlq, stop),
            name="state",
        ),
    ]
    for metric in discover_metrics():
        if metric.event_types:
            tasks.append(
                asyncio.create_task(
                    _consume_metric(
                        kafka_url,
                        f"tidemill.metric.{metric.name}",
                        metric.name,
                        factory,
                        dlq,
                        stop,
                    ),
                    name=f"metric.{metric.name}",
                )
            )

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
    from tidemill.state import handle_state_event

    consumer = EventConsumer(
        bootstrap_servers=kafka_url,
        group_id="tidemill.state",
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
                await _maybe_mark_resolved(factory, event.id, "state")
            except Exception as exc:
                logger.exception("State consumer error for event %s", event.id)
                await _dead_letter(factory, dlq, event, "state", exc)
                await consumer.commit()
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
    from tidemill.metrics.registry import discover_metrics

    metrics = {m.name: m for m in discover_metrics()}
    metric = metrics[metric_name]
    consumer_tag = f"metric:{metric_name}"

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
                await _maybe_mark_resolved(factory, event.id, consumer_tag)
            except Exception as exc:
                logger.exception("Metric %s consumer error for event %s", metric_name, event.id)
                await _dead_letter(factory, dlq, event, consumer_tag, exc)
                await consumer.commit()
    finally:
        await consumer.stop()


async def _dead_letter(
    factory: async_sessionmaker[AsyncSession],
    dlq: EventProducer,
    event: Event,
    consumer: str,
    error: BaseException,
) -> None:
    """Persist a dead-letter row and mirror to the Kafka DLQ topic.

    Uses a fresh DB session because the handler's session has been rolled
    back. Failures here are logged but never re-raised — the worker must
    keep consuming.
    """
    from tidemill.dead_letter import record

    try:
        async with factory() as session:
            await record(session, event, consumer, error)
    except Exception:
        logger.exception("Failed to record dead-letter row for event %s (%s)", event.id, consumer)

    try:
        await dlq.publish(event)
    except Exception:
        logger.exception("Failed to send event %s to Kafka DLQ", event.id)


async def _maybe_mark_resolved(
    factory: async_sessionmaker[AsyncSession],
    event_id: str,
    consumer: str,
) -> None:
    """Best-effort resolve any prior dead-letter row for this (event, consumer).

    Cheap UPDATE that no-ops when the row doesn't exist or is already
    resolved. Errors are swallowed — successful event processing must
    never fail because of dead-letter bookkeeping.
    """
    from tidemill.dead_letter import mark_resolved

    try:
        async with factory() as session:
            await mark_resolved(session, event_id, consumer)
    except Exception:
        logger.debug(
            "Could not mark dead-letter resolved for event %s (%s)",
            event_id,
            consumer,
            exc_info=True,
        )


if __name__ == "__main__":
    asyncio.run(run_worker())
