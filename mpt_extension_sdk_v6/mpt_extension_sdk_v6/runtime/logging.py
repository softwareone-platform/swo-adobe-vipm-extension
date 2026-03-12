import contextvars
import json
import os
from logging import Filter, Formatter, LogRecord, config
from typing import Any

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

        Builds a compact ``request_context`` string for the text formatter and
        sets individual attributes for the JSON formatter.

        Args:
            record: The log record to enrich.

        Returns:
            Always True so the record is not suppressed.
        """
        correlation_id = correlation_id_ctx.get()
        task_id = task_id_ctx.get()
        obj_type, obj_id = object_ctx.get()

        record.correlation_id = correlation_id  # type: ignore[attr-defined]
        record.task_id = task_id  # type: ignore[attr-defined]
        record.object_type = obj_type  # type: ignore[attr-defined]
        record.object_id = obj_id  # type: ignore[attr-defined]

        parts = [f"[{correlation_id}]"] if correlation_id else []
        if task_id:
            parts.append(f"[task: {task_id}]")
        if obj_type and obj_id:
            parts.append(f"[{obj_type}: {obj_id}]")
        record.request_context = " ".join(parts)  # type: ignore[attr-defined]

        return True


class JsonFormatter(Formatter):
    """Formats log records as newline-delimited JSON for structured log ingestion."""

    def format(self, record: LogRecord) -> str:
        """Serialize a log record to a JSON string.

        Args:
            record: The log record to format.

        Returns:
            A JSON-encoded string representing the log record.
        """
        data: dict[str, Any] = {
            "time": self.formatTime(record),
            "level": record.levelname,
            "name": record.name,
            "pid": record.process,
            "correlation_id": getattr(record, "correlation_id", ""),
            "task_id": getattr(record, "task_id", ""),
            "message": record.getMessage(),
        }
        obj_type = getattr(record, "object_type", "").lower()
        obj_id = getattr(record, "object_id", "")
        if obj_type and obj_id:
            data[obj_type] = obj_id
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data)


def get_logging_config(log_level: str, *, json_format: bool = False) -> dict[str, Any]:
    """Return a logging configuration dictionary compatible with dictConfig.

    Args:
        log_level: Root log level string (e.g. ``"INFO"``, ``"DEBUG"``).
        json_format: When True, emit JSON-formatted records instead of plain text.

    Returns:
        A dict ready to pass to ``logging.config.dictConfig``.
    """
    if json_format:
        formatter_config: dict[str, Any] = {
            "()": "mpt_extension_sdk_v6.runtime.logging.JsonFormatter",
        }
    else:
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
    """Initialise process-wide logging.

    Args:
        log_level: Root log level string. Defaults to ``"INFO"``.
            Set ``LOG_FORMAT=json`` in the environment to emit JSON records.
    """
    json_format = os.getenv("LOG_FORMAT", "").lower() == "json"
    config.dictConfig(get_logging_config(log_level=log_level, json_format=json_format))
