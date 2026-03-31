import contextvars
import json
import os
from logging import Filter, Formatter, LogRecord, config
from typing import Any, override

correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)
task_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("task_id", default="")
object_ctx: contextvars.ContextVar[tuple[str, str]] = contextvars.ContextVar(
    "object", default=("", "")
)


class CorrelationIdFilter(Filter):
    """Injects request-scoped context fields into every log record."""

    def filter(self, record: LogRecord) -> bool:
        """Enrich the log record with correlation ID, task ID, and object info.

        Builds a compact `request_context` string for the text formatter and
        sets individual attributes for the JSON formatter.

        Args:
            record: The log record to enrich.

        Returns:
            Always True so the record is not suppressed.
        """
        correlation_id = correlation_id_ctx.get()
        task_id = task_id_ctx.get()
        obj_type, obj_id = object_ctx.get()

        record.correlation_id = correlation_id
        record.task_id = task_id
        record.object_type = obj_type
        record.object_id = obj_id
        record.trace_id = getattr(record, "otelTraceID", "")
        record.span_id = getattr(record, "otelSpanID", "")

        parts = [f"[{correlation_id}]"] if correlation_id else []
        if task_id:
            parts.append(f"[task: {task_id}]")
        if obj_type and obj_id:
            parts.append(f"[{obj_type}: {obj_id}]")
        if record.trace_id:
            parts.append(f"[trace: {record.trace_id}]")
        record.request_context = " ".join(parts)

        return True


def get_logging_config(log_level: str) -> dict[str, Any]:
    """Return a logging configuration dictionary compatible with dictConfig.

    Args:
        log_level: Root log level string (e.g. `"INFO"`, `"DEBUG"`).

    Returns:
        A dict ready to pass to `logging.config.dictConfig`.
    """
    formatter_config = {
        "format": "{asctime} {name} {levelname} (pid: {process}) {request_context} {message}",
        "style": "{",
    }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "correlation_id": {
                "()": "mpt_extension_sdk_v6.runtime.logging.CorrelationIdFilter",
            },
        },
        "formatters": {
            "verbose": formatter_config,
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "verbose",
                "filters": ["correlation_id"],
                "stream": "ext://sys.stderr",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": log_level,
        },
        "loggers": {
            "mpt_extension_sdk_v6": {
                "handlers": ["console"],
                "level": log_level,
                "propagate": False,
            },
        },
    }


def setup_logging(log_level: str = "INFO") -> None:
    """Initialize process-wide logging.

    Args:
        log_level: Root log level string. Defaults to `"INFO"`.
    """
    config.dictConfig(get_logging_config(log_level=log_level))
