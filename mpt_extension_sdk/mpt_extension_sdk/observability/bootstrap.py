import importlib
from threading import Lock

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

from mpt_extension_sdk.errors.runtime import ConfigError
from mpt_extension_sdk.observability.config import ObservabilityConfig


class ObservabilityBootstrap:
    """Thread-safe singleton-style bootstrapper for SDK observability."""

    _lock = Lock()
    _initialized = False
    _fast_api_instrumented = False

    @classmethod
    def bootstrap(cls, config: ObservabilityConfig) -> None:
        """Initialize the process-wide tracing provider and instruments once."""
        if not config.enabled:
            return

        with cls._lock:
            if cls._initialized:
                return

            provider = TracerProvider(
                resource=Resource.create({"service.name": config.service_name})
            )
            for exporter_name in config.exporters:
                exporter = cls._build_exporter(exporter_name, config)
                if exporter is not None:
                    provider.add_span_processor(BatchSpanProcessor(exporter))

            trace.set_tracer_provider(provider)
            LoggingInstrumentor().instrument(set_logging_format=False)
            HTTPXClientInstrumentor().instrument()
            cls._initialized = True

    @classmethod
    def instrument_fastapi_app(cls, app: FastAPI, config: ObservabilityConfig) -> None:
        """Instrument a FastAPI app instance when observability is enabled."""
        if not config.enabled:
            return

        with cls._lock:
            if cls._fast_api_instrumented:
                return

            cls._fast_api_instrumented = True
            FastAPIInstrumentor.instrument_app(app)

    @classmethod
    def _build_exporter(cls, exporter_name: str, config: ObservabilityConfig) -> SpanExporter:
        """Return the configured trace exporter instance for the given name."""
        if exporter_name == "otlp":
            return OTLPSpanExporter()
        if exporter_name == "azure_monitor":
            return cls._build_azure_monitor_exporter(config)

        raise ConfigError(f"Unsupported OpenTelemetry exporter: {exporter_name}")

    @classmethod
    def _build_azure_monitor_exporter(cls, config: ObservabilityConfig) -> SpanExporter:
        """Create the Azure Monitor exporter or raise a helpful config error."""
        if not config.applicationinsights_connection_string:
            raise ConfigError(
                "Azure Monitor exporter requires the applicationinsights_connection_string "
                "setting to be set"
            )

        try:
            module = importlib.import_module("azure.monitor.opentelemetry.exporter")
        except ModuleNotFoundError as error:
            raise ConfigError(
                "Azure Monitor exporter requires the optional dependency "
                "'mpt-extension-sdk[azure-monitor]'"
            ) from error

        return module.AzureMonitorTraceExporter(
            connection_string=config.applicationinsights_connection_string,
        )
