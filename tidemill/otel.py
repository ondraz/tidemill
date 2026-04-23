"""OpenTelemetry bootstrap for API and worker processes.

Wiring is guarded by :attr:`OtelConfig.enabled`. When disabled, :func:`init_otel`
is a no-op — imports are deferred so the observability extra is only required
at install time when the user opts in.
"""

from __future__ import annotations

import logging
from typing import Any

from tidemill.config import OtelConfig

logger = logging.getLogger(__name__)

_initialized: bool = False


def _install_trace_log_factory(service_name: str) -> None:
    """Attach otelTraceID / otelSpanID / otelServiceName to every LogRecord.

    LoggingInstrumentor only populates these fields when ``set_logging_format=True``,
    which forces :func:`logging.basicConfig` and overrides our formatter. We install
    our own factory so the formatter stays in our control.
    """
    from opentelemetry import trace

    old_factory = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = old_factory(*args, **kwargs)
        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx is not None and ctx.is_valid:
            record.otelTraceID = format(ctx.trace_id, "032x")
            record.otelSpanID = format(ctx.span_id, "016x")
        else:
            record.otelTraceID = ""
            record.otelSpanID = ""
        record.otelServiceName = service_name
        return record

    logging.setLogRecordFactory(factory)


def init_otel(service_name: str) -> None:
    """Initialize tracer/meter providers and auto-instrumentation.

    Args:
        service_name: Value for the ``service.name`` resource attribute
            (e.g. ``tidemill-api``, ``tidemill-worker``). Overrides
            ``OTEL_SERVICE_NAME`` from the environment.
    """
    global _initialized
    if _initialized:
        return

    cfg = OtelConfig()
    if not cfg.enabled:
        logger.debug("OTEL disabled; skipping instrumentation")
        return

    try:
        from opentelemetry import metrics, trace
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "OTEL enabled but opentelemetry packages are missing. "
            "Install the `observability` extra (uv sync --extra observability).",
        )
        return

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": _package_version(),
            "deployment.environment": cfg.environment,
        },
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=cfg.exporter_endpoint, insecure=True)),
    )
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[
            PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=cfg.exporter_endpoint, insecure=True),
            ),
        ],
    )
    metrics.set_meter_provider(meter_provider)

    # Attach trace_id / span_id to every LogRecord without touching the formatter.
    _install_trace_log_factory(service_name)

    AIOKafkaInstrumentor().instrument()

    _initialized = True
    logger.info(
        "OTEL initialized service=%s endpoint=%s environment=%s",
        service_name,
        cfg.exporter_endpoint,
        cfg.environment,
    )


def instrument_sqlalchemy(engine: Any) -> None:
    """Emit a span per SQL statement for *engine*.

    Called after each async engine is created. Passes the underlying sync
    engine because SQLAlchemyInstrumentor hooks ``before_cursor_execute`` on
    the sync ``Engine`` — reliably capturing SELECT/INSERT/UPDATE with full
    SQL text in ``db.statement``. When ``TIDEMILL_OTEL_CAPTURE_PARAMS`` is
    enabled, bound parameter values are attached as ``db.statement.parameters``
    — leave off in production to avoid leaking PII into traces.
    """
    cfg = OtelConfig()
    if not cfg.enabled:
        return
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    except ImportError:
        return
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine,
        enable_commenter=True,
    )
    if cfg.capture_params:
        _attach_param_listener(engine.sync_engine)


def _attach_param_listener(sync_engine: Any) -> None:
    """Add bound parameter values to the DB span as ``db.statement.parameters``.

    Runs on ``after_cursor_execute`` so the span created by
    SQLAlchemyInstrumentor is available on ``context._otel_span``.
    """
    from sqlalchemy import event

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before_cursor_execute(
        conn: Any,  # noqa: ARG001
        cursor: Any,  # noqa: ARG001
        statement: str,  # noqa: ARG001
        parameters: Any,
        context: Any,
        executemany: bool,  # noqa: ARG001
    ) -> None:
        span = getattr(context, "_otel_span", None)
        if span is None or not span.is_recording():
            return
        span.set_attribute("db.statement.parameters", repr(parameters))


def instrument_fastapi(app: object) -> None:
    """Install FastAPI request/response span instrumentation.

    Called after ``FastAPI()`` is constructed. No-op when OTEL is disabled.
    """
    if not OtelConfig.enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    except ImportError:
        return
    FastAPIInstrumentor.instrument_app(app)  # type: ignore[arg-type]


def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("tidemill")
    except Exception:
        return "0.0.0"
