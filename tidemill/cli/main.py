"""CLI entry point — Typer commands wrapping MetricsEngine."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import date
from typing import Any

import typer

app = typer.Typer(name="tidemill", help="Subscription analytics engine.")


def _db_url() -> str:
    return os.environ.get(
        "TIDEMILL_DATABASE_URL",
        "postgresql+asyncpg://localhost/tidemill",
    )


def _kafka_url() -> str:
    return os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")


async def _query(metric: str, params: dict[str, Any], spec: Any = None) -> Any:
    from tidemill.database import make_engine, make_session_factory
    from tidemill.engine import MetricsEngine

    engine = make_engine(_db_url())
    factory = make_session_factory(engine)
    async with factory() as session:
        me = MetricsEngine(db=session)
        result = await me.query(metric, params, spec)
    await engine.dispose()
    return result


def _build_spec(
    dimensions: list[str] | None,
    filters: list[str] | None,
) -> Any:
    from tidemill.metrics.base import QuerySpec

    filt: dict[str, Any] = {}
    for f in filters or []:
        key, _, value = f.partition("=")
        filt[key] = value
    if not dimensions and not filt:
        return None
    return QuerySpec(dimensions=dimensions or [], filters=filt)


def _output(result: Any, fmt: str) -> None:
    if fmt == "json":
        typer.echo(json.dumps(result, default=str, indent=2))
    elif fmt == "csv":
        if isinstance(result, list) and result:
            keys = result[0].keys()
            typer.echo(",".join(keys))
            for row in result:
                typer.echo(",".join(str(row.get(k, "")) for k in keys))
        else:
            typer.echo(str(result))
    else:
        if isinstance(result, list):
            for row in result:
                typer.echo(row)
        else:
            typer.echo(result)


@app.command()
def mrr(
    at: str | None = typer.Option(None, help="Point-in-time date (YYYY-MM-DD)"),
    start: str | None = typer.Option(None, help="Series start date"),
    end: str | None = typer.Option(None, help="Series end date"),
    interval: str = typer.Option("month", help="Series interval"),
    dimension: list[str] | None = typer.Option(None, help="Group-by dimensions"),
    filter: list[str] | None = typer.Option(None, help="Filters (key=value)"),
    format: str = typer.Option("text", help="Output format: text, json, csv"),
) -> None:
    """Query MRR."""
    spec = _build_spec(dimension, filter)
    if start and end:
        params: dict[str, Any] = {
            "query_type": "series",
            "start": date.fromisoformat(start),
            "end": date.fromisoformat(end),
            "interval": interval,
        }
    else:
        params = {
            "query_type": "current",
            "at": date.fromisoformat(at) if at else None,
        }
    result = asyncio.run(_query("mrr", params, spec))
    _output(result, format)


@app.command()
def churn(
    start: str = typer.Option(..., help="Start date"),
    end: str = typer.Option(..., help="End date"),
    type: str = typer.Option("logo", help="Churn type: logo or revenue"),
    dimension: list[str] | None = typer.Option(None),
    filter: list[str] | None = typer.Option(None),
    format: str = typer.Option("text"),
) -> None:
    """Query churn rate."""
    spec = _build_spec(dimension, filter)
    params: dict[str, Any] = {
        "start": date.fromisoformat(start),
        "end": date.fromisoformat(end),
        "type": type,
    }
    result = asyncio.run(_query("churn", params, spec))
    _output(result, format)


@app.command()
def retention(
    start: str = typer.Option(..., help="Start date"),
    end: str = typer.Option(..., help="End date"),
    query_type: str = typer.Option("cohort_matrix"),
    dimension: list[str] | None = typer.Option(None),
    filter: list[str] | None = typer.Option(None),
    format: str = typer.Option("text"),
) -> None:
    """Query retention."""
    spec = _build_spec(dimension, filter)
    params: dict[str, Any] = {
        "query_type": query_type,
        "start": date.fromisoformat(start),
        "end": date.fromisoformat(end),
    }
    result = asyncio.run(_query("retention", params, spec))
    _output(result, format)


@app.command("metrics")
def list_metrics() -> None:
    """List available metrics."""
    from tidemill.metrics.registry import discover_metrics

    for m in sorted(discover_metrics(), key=lambda x: x.name):
        typer.echo(m.name)


@app.command("init-db")
def init_db() -> None:
    """Create all database tables."""

    async def _init() -> None:
        from sqlalchemy.ext.asyncio import create_async_engine

        from tidemill.models import metadata

        engine = create_async_engine(_db_url())
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        await engine.dispose()
        typer.echo("Tables created.")

    asyncio.run(_init())


@app.command()
def backfill(
    source: str = typer.Option(..., help="Source name or ID"),
) -> None:
    """Run a backfill for a connector source."""

    async def _backfill() -> None:
        import json as _json

        from sqlalchemy import text

        from tidemill.bus import EventProducer
        from tidemill.connectors import get_connector
        from tidemill.database import make_engine, make_session_factory

        engine = make_engine(_db_url())
        factory = make_session_factory(engine)
        async with factory() as session:
            result = await session.execute(
                text(
                    "SELECT id, type, config FROM connector_source"
                    " WHERE id = :s OR name = :s LIMIT 1"
                ),
                {"s": source},
            )
            row = result.fetchone()
            if not row:
                typer.echo(f"Source not found: {source}", err=True)
                raise typer.Exit(1)
            source_id, source_type, config_str = row
            config = _json.loads(config_str) if config_str else {}

        connector = get_connector(source_type, source_id=source_id, config=config)
        producer = EventProducer(bootstrap_servers=_kafka_url())
        await producer.start()
        count = 0
        async for event in connector.backfill():
            await producer.publish(event)
            count += 1
        await producer.stop()
        await engine.dispose()
        typer.echo(f"Backfill complete: {count} events published.")

    asyncio.run(_backfill())


@app.command("fx-sync")
def fx_sync(
    since: str | None = typer.Option(
        None,
        "--since",
        help=(
            "ISO date (YYYY-MM-DD) to backfill from, overriding the per-currency"
            " last-synced cursor. Use this when seeding historical data — the"
            " default incremental sync only pulls forward from the most recent"
            " stored rate, which leaves older gaps unfilled."
        ),
    ),
) -> None:
    """Fetch missing FX rates from Frankfurter and upsert into ``fx_rate``.

    Default behavior is incremental: only days after each currency's most
    recent stored rate are fetched. Pass ``--since`` to force a backfill
    from a specific date (idempotent — existing rows are upserted).

    Use this from seed scripts before generating historical data and from
    cron for redundancy with the API/worker background loop.
    """
    from datetime import date as _date

    parsed_since: _date | None = None
    if since:
        try:
            parsed_since = _date.fromisoformat(since)
        except ValueError as exc:
            typer.echo(f"Invalid --since (expected YYYY-MM-DD): {exc}", err=True)
            raise typer.Exit(2) from exc

    async def _run() -> None:
        from tidemill.database import make_engine, make_session_factory
        from tidemill.fx_sync import sync_fx_rates

        engine = make_engine(_db_url())
        factory = make_session_factory(engine)
        async with factory() as session:
            n = await sync_fx_rates(session, since=parsed_since)
            await session.commit()
        await engine.dispose()
        typer.echo(f"fx-sync: wrote {n} rows")

    asyncio.run(_run())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8000, help="Bind port"),
) -> None:
    """Start the HTTP API server."""
    import uvicorn

    uvicorn.run("tidemill.api.app:app", host=host, port=port)


@app.command()
def worker() -> None:
    """Start the Kafka worker process."""
    from tidemill.worker import run_worker

    asyncio.run(run_worker())


@app.command("dlq-list")
def dlq_list(
    consumer: str | None = typer.Option(None, help="Filter by consumer (e.g. metric:mrr)"),
    error_type: str | None = typer.Option(None, help="Filter by error_type"),
    unresolved_only: bool = typer.Option(True, help="Hide rows already replayed"),
    limit: int = typer.Option(50),
) -> None:
    """List dead-lettered events (failed handler runs awaiting replay)."""

    async def _run() -> None:
        from sqlalchemy import text

        from tidemill.database import make_engine, make_session_factory

        engine = make_engine(_db_url())
        factory = make_session_factory(engine)
        sql = (
            "SELECT event_id, consumer, event_type, error_type, error_message,"
            " occurred_at, dead_lettered_at, resolved_at"
            " FROM dead_letter_event WHERE 1=1"
        )
        params: dict[str, Any] = {"lim": limit}
        if consumer:
            sql += " AND consumer = :consumer"
            params["consumer"] = consumer
        if error_type:
            sql += " AND error_type = :err"
            params["err"] = error_type
        if unresolved_only:
            sql += " AND resolved_at IS NULL"
        sql += " ORDER BY dead_lettered_at DESC LIMIT :lim"
        async with factory() as session:
            rows = (await session.execute(text(sql), params)).mappings().all()
        await engine.dispose()
        if not rows:
            typer.echo("(none)")
            return
        for r in rows:
            typer.echo(
                f"[{r['dead_lettered_at'].isoformat()}] {r['consumer']:14}"
                f" {r['error_type']:18} {r['event_id']}  {r['event_type']}"
            )
            typer.echo(f"  {r['error_message']}")

    asyncio.run(_run())


@app.command("dlq-replay")
def dlq_replay(
    consumer: str | None = typer.Option(None, help="Restrict to this consumer"),
    error_type: str | None = typer.Option(None, help="Restrict to this error_type"),
) -> None:
    """Re-publish unresolved dead-letter events back to Kafka.

    The worker picks them up on its normal topic. Rows whose handler now
    succeeds get their ``resolved_at`` set the next time the failure clears.
    """

    async def _run() -> None:
        import json as _json

        from sqlalchemy import text

        from tidemill.bus import EventProducer
        from tidemill.database import make_engine, make_session_factory
        from tidemill.events import Event

        engine = make_engine(_db_url())
        factory = make_session_factory(engine)
        sql = (
            "SELECT event_id, source_id, event_type, payload, occurred_at"
            " FROM dead_letter_event WHERE resolved_at IS NULL"
        )
        params: dict[str, Any] = {}
        if consumer:
            sql += " AND consumer = :consumer"
            params["consumer"] = consumer
        if error_type:
            sql += " AND error_type = :err"
            params["err"] = error_type
        async with factory() as session:
            rows = (await session.execute(text(sql), params)).mappings().all()
        if not rows:
            typer.echo("Nothing to replay.")
            await engine.dispose()
            return
        producer = EventProducer(bootstrap_servers=_kafka_url())
        await producer.start()
        for r in rows:
            payload = _json.loads(r["payload"])
            event = Event(
                id=r["event_id"],
                source_id=r["source_id"],
                type=r["event_type"],
                occurred_at=r["occurred_at"],
                published_at=r["occurred_at"],
                customer_id=payload.get("customer_id", ""),
                payload=payload,
            )
            await producer.publish(event)
        await producer.stop()
        await engine.dispose()
        typer.echo(f"Replayed {len(rows)} event(s) to Kafka.")

    asyncio.run(_run())


cli = app
