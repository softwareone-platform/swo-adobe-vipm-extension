import logging
from functools import wraps
from urllib.parse import urljoin

from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from django.conf import settings
from django.utils.module_loading import import_string
from opentelemetry import trace
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from requests import Session as _Session
from requests.adapters import HTTPAdapter, Retry

logger = logging.getLogger(__name__)


class Session(_Session):
    def __init__(self, base_url):
        super().__init__()
        self.base_url = f"{base_url}/" if base_url[-1] != "/" else base_url

    def request(self, method, url, *args, **kwargs):
        url = self.join_url(url)
        return super().request(method, url, *args, **kwargs)

    def prepare_request(self, request, *args, **kwargs):
        request.url = self.join_url(request.url)
        return super().prepare_request(request, *args, **kwargs)

    def join_url(self, url):
        url = url[1:] if url[0] == "/" else url
        return urljoin(self.base_url, url)


def setup_client():
    session = Session(f"{settings.MPT_API_BASE_URL}/v1/")
    retries = Retry(
        total=5,
        backoff_factor=0.1,
        status_forcelist=[500, 502, 503, 504],
    )
    session.mount("http://", HTTPAdapter(max_retries=retries))
    session.headers.update(
        {"Authorization": f"Bearer {settings.MPT_API_TOKEN}", "User-Agent": "swo-extensions/1.0"}
    )
    return session


def _response_hook(span, request, response):
    if not response.ok:
        span.set_attribute("http.error", response.content)


def instrument_logging():
    resource = Resource(
        attributes={
            "service.name": settings.SERVICE_NAME,
        }
    )

    if settings.USE_APPLICATIONINSIGHTS:
        exporter = AzureMonitorTraceExporter(
            connection_string=settings.APPLICATIONINSIGHTS_CONNECTION_STRING
        )
    else:
        exporter = ConsoleSpanExporter()

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
            attempt_func = lambda _: 0

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
