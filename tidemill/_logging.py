"""Shared stdout logging setup for API and worker processes."""

from __future__ import annotations

import logging
import os


class _TraceContextFilter(logging.Filter):
    """Provide empty-string fallbacks for OTEL log record fields.

    LoggingInstrumentor attaches otelTraceID/otelSpanID/otelServiceName via a
    record factory when tracing is active. When OTEL is disabled those fields
    are missing and %-formatting would raise. This filter injects empty
    defaults so the same format string works in both modes.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for attr in ("otelTraceID", "otelSpanID", "otelServiceName"):
            if not hasattr(record, attr):
                setattr(record, attr, "")
        return True


def _make_handler() -> logging.Handler:
    from uvicorn.logging import DefaultFormatter

    handler = logging.StreamHandler()
    handler.setFormatter(
        DefaultFormatter(
            fmt=(
                "%(levelprefix)s %(name)s "
                "[trace_id=%(otelTraceID)s span_id=%(otelSpanID)s] - %(message)s"
            ),
        ),
    )
    handler.addFilter(_TraceContextFilter())
    return handler


def configure_logging(service_name: str) -> None:
    """Configure the `tidemill` logger with a shared formatter.

    Also rewires uvicorn's loggers (``uvicorn``, ``uvicorn.access``,
    ``uvicorn.error``) to use the same handler so request access logs
    include trace_id/span_id like every other log line.
    """
    log_level = os.environ.get("TIDEMILL_LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, log_level, logging.DEBUG)

    def _install(name: str, lvl: int) -> None:
        lg = logging.getLogger(name)
        lg.setLevel(lvl)
        for h in list(lg.handlers):
            lg.removeHandler(h)
        lg.addHandler(_make_handler())
        lg.propagate = False

    _install("tidemill", level)
    _install("uvicorn", logging.INFO)
    _install("uvicorn.error", logging.INFO)
    _install("uvicorn.access", logging.INFO)

    logging.getLogger("tidemill").debug("Logging configured for service=%s", service_name)
