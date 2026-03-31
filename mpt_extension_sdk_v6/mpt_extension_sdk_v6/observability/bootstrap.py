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

from mpt_extension_sdk_v6.errors.runtime import ConfigError
from mpt_extension_sdk_v6.observability.config import ObservabilityConfig


class ObservabilityBootstrap:
    """Thread-safe singleton-style bootstrapper for SDK observability."""

    _lock = Lock()
    _initialized = False

    @classmethod
    def bootstrap(cls, config: ObservabilityConfig) -> None:
        """Initialize the process-wide tracing provider and instrumentors once."""
        if not config.enabled:
            return

        with cls._lock:
            if cls._initialized:
                return

            provider = TracerProvider(
                resource=Resource.create({"service.name": config.service_name}),
            )
            for exporter_name in config.exporters:
                provider.add_span_processor(BatchSpanProcessor(cls._build_exporter(exporter_name)))

            trace.set_tracer_provider(provider)
            LoggingInstrumentor().instrument(set_logging_format=False)
            HTTPXClientInstrumentor().instrument()
            cls._initialized = True

    @classmethod
    def instrument_fastapi_app(cls, app: FastAPI, config: ObservabilityConfig) -> None:
        """Instrument a FastAPI app instance when observability is enabled."""
        if not config.enabled:
            return
        if getattr(app.state, "sdk_fastapi_instrumented", False):
            return

        FastAPIInstrumentor.instrument_app(app)
        app.state.sdk_fastapi_instrumented = True

    @classmethod
    def _build_exporter(cls, exporter_name: str) -> SpanExporter:
        """Return the configured trace exporter instance for the given name."""
        if exporter_name == "otlp":
            return OTLPSpanExporter()
        if exporter_name == "azure_monitor":
            return cls._build_azure_monitor_exporter()

        raise ConfigError(f"Unsupported OpenTelemetry exporter: {exporter_name}")

    @classmethod
    def _build_azure_monitor_exporter(cls) -> object:
        """Create the Azure Monitor exporter or raise a helpful config error."""
        try:
            module = importlib.import_module("azure.monitor.opentelemetry.exporter")
        except ModuleNotFoundError as error:
            raise ConfigError(
                "Azure Monitor exporter requires the optional dependency "
                "'mpt-extension-sdk-v6[azure-monitor]'"
            ) from error

        return module.AzureMonitorTraceExporter()
