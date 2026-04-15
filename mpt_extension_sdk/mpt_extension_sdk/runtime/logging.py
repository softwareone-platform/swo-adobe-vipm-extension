import contextvars
import os
from importlib import import_module
from logging import Filter, Handler, Logger, LogRecord, config, getLogger
from typing import Any, override

from mpt_extension_sdk.errors.runtime import ConfigError

correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)
task_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("task_id", default="")
order_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("order_id", default="")
agreement_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("agreement_id", default="")


def set_event_context(*, task_id: str = "", order_id: str = "", agreement_id: str = "") -> None:
    """Persist entity identifiers for the current event execution."""
    agreement_id_ctx.set(agreement_id)
    order_id_ctx.set(order_id)
    task_id_ctx.set(task_id)


class CorrelationIdFilter(Filter):
    """Injects request-scoped context fields into every log record."""

    @override
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
        record.correlation_id = correlation_id
        task_id = task_id_ctx.get()
        record.task_id = task_id
        record.order_id = order_id_ctx.get()
        record.agreement_id = agreement_id_ctx.get()
        record.trace_id = getattr(record, "otelTraceID", "")
        record.span_id = getattr(record, "otelSpanID", "")

        parts = [f"({task_id})"] if task_id else []
        if record.order_id:
            parts.append(f"(order: {record.order_id})")
        if record.agreement_id:
            parts.append(f"(agreement: {record.agreement_id})")
        if record.trace_id:
            parts.append(f"(trace: {record.trace_id})")
        record.request_context = " ".join(parts)

        return True


def get_logging_config(log_level: str, ext_package: str | None = None) -> dict[str, Any]:
    """Return a logging configuration dictionary compatible with dictConfig.

    Args:
        log_level: Root log level string (e.g. `"INFO"`, `"DEBUG"`).
        ext_package: The name of the extension package.

    Returns:
        A dict ready to pass to `logging.config.dictConfig`.
    """
    formatter_config = {
        "format": "{asctime} {name} {levelname} (pid: {process}) {request_context} {message}",
        "style": "{",
    }

    loggers = {
        "mpt_extension_sdk": {
            "handlers": ["console"],
            "level": log_level,
            "propagate": False,
        },
    }
    if ext_package:
        loggers[ext_package] = {
            "handlers": ["console"],
            "level": log_level,
            "propagate": False,
        }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "correlation_id": {
                "()": "mpt_extension_sdk.runtime.logging.CorrelationIdFilter",
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
            "level": "WARNING",
        },
        "loggers": loggers,
    }


def get_azure_monitor_handler() -> Handler | None:
    """Return an optional Azure Monitor log handler when configured."""
    if os.getenv("SDK_OBSERVABILITY_ENABLED", "true").lower() not in {"true", "1", "yes"}:
        return None

    connection_string = os.getenv("SDK_APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    if not connection_string:
        return None

    try:
        azure_exporter_module = import_module("azure.monitor.opentelemetry.exporter")
        logs_module = import_module("opentelemetry.sdk._logs")
        logs_export_module = import_module("opentelemetry.sdk._logs.export")
        resources_module = import_module("opentelemetry.sdk.resources")
    except ModuleNotFoundError:
        return None

    logger_provider = logs_module.LoggerProvider(
        resource=resources_module.Resource.create(
            {"service.name": _resolve_logging_service_name()},
        ),
    )
    logger_provider.add_log_record_processor(
        logs_export_module.BatchLogRecordProcessor(
            azure_exporter_module.AzureMonitorLogExporter(
                connection_string=connection_string,
            ),
        )
    )
    return logs_module.LoggingHandler(level=0, logger_provider=logger_provider)


def setup_logging(log_level: str = "INFO", ext_package: str | None = None) -> None:
    """Initialize process-wide logging.

    Args:
        log_level: Root log level string. Defaults to `"INFO"`.
        ext_package: The name of the extension package.
    """
    config.dictConfig(get_logging_config(log_level=log_level, ext_package=ext_package))
    azure_handler = get_azure_monitor_handler()
    if azure_handler is None:
        return

    azure_handler.addFilter(CorrelationIdFilter())
    _attach_handler_once(getLogger(), azure_handler)
    _attach_handler_once(getLogger("mpt_extension_sdk"), azure_handler)


def _resolve_logging_service_name() -> str:
    """Return the service name used by the optional Azure log exporter."""
    configured = os.getenv("SDK_OTEL_SERVICE_NAME", "")
    if configured:
        return configured

    raise ConfigError("SDK_OTEL_SERVICE_NAME is required when SDK_OBSERVABILITY_ENABLED is enabled")


def _attach_handler_once(logger: Logger, log_handler: Handler) -> None:
    """Attach a handler only if an equivalent handler has not been added yet."""
    handler_type = type(log_handler)
    if any(isinstance(existing, handler_type) for existing in logger.handlers):
        return
    logger.addHandler(log_handler)
