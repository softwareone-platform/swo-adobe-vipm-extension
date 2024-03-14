import logging
from functools import wraps

from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from django.conf import settings
from django.utils.module_loading import import_string
from opentelemetry import trace
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from swo.mpt.client import MPTClient

logger = logging.getLogger(__name__)


def setup_client():
    return MPTClient(
        f"{settings.MPT_API_BASE_URL}/v1/",
        settings.MPT_LOGIN_URL,
        settings.MPT_AUTH0_CLIENT_ID,
        settings.MPT_USERNAME,
        settings.MPT_API_TOKEN,  # w/a replace with MPT_PASSWORD later
    )


def _response_hook(span, request, response):
    if not response.ok:
        span.set_attribute("http.error", response.content)


def instrument_logging():
    resource = Resource(
        attributes={
            "service.name": settings.SERVICE_NAME,
        }
    )

    exporter = AzureMonitorTraceExporter(
        connection_string=settings.APPLICATIONINSIGHTS_CONNECTION_STRING
    )

    trace_provider = TracerProvider(resource=resource)
    trace_provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(trace_provider)

    DjangoInstrumentor().instrument()
    RequestsInstrumentor().instrument(response_hook=_response_hook)
    LoggingInstrumentor().instrument()


def wrap_for_trace(func, event_type):
    @wraps(func)
    def opentelemetry_wrapper(client, event):
        tracer = trace.get_tracer(event_type)
        object_id = event.id

        try:
            attempt_func = import_string(settings.LOGGING_ATTEMPT_GETTER)
        except ImportError:
            attempt_func = lambda _: 0  # noqa: E731

        attempt = attempt_func(event)
        with tracer.start_as_current_span(
            f"Event {event_type} for {object_id} attempt {attempt}"
        ) as span:
            try:
                func(client, event)
            except Exception:
                logger.exception("Unhandled exception!")
            finally:
                if span.is_recording():
                    span.set_attribute("order.id", object_id)
                    span.set_attribute("attempt", attempt)

    @wraps(func)
    def wrapper(client, event):
        try:
            func(client, event)
        except Exception:
            logger.exception("Unhandled exception!")

    return opentelemetry_wrapper if settings.USE_APPLICATIONINSIGHTS else wrapper
