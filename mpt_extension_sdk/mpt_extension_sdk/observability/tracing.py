from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry.context import Context
from opentelemetry.trace import Span, SpanKind, get_tracer

TRACER = get_tracer("mpt_extension_sdk")
type AttributeValue = str | int | float | bool
type Attributes = dict[str, AttributeValue]


@contextmanager
def start_event_span(path: str, *, task_based: bool, event: Any) -> Iterator[Span]:
    """Start and yield the root span for an incoming event delivery."""
    object_type = getattr(getattr(event, "object", None), "object_type", "")
    object_id = getattr(getattr(event, "object", None), "id", "")
    event_type = getattr(getattr(event, "details", None), "event_type", "")
    business_attributes: Attributes = {}
    if object_type == "Order" and object_id:
        business_attributes["order.id"] = object_id
    if object_type == "Agreement" and object_id:
        business_attributes["agreement.id"] = object_id
    span_name = _build_event_span_name(object_type, object_id)
    with TRACER.start_as_current_span(span_name, context=Context(), kind=SpanKind.SERVER) as span:
        set_attributes(
            span,
            {
                "mpt.extension.route_path": path,
                "mpt.extension.task_based": task_based,
                "mpt.event.id": getattr(event, "id", ""),
                "mpt.event.type": event_type,
                "mpt.task.id": getattr(getattr(event, "task", None), "id", ""),
                **business_attributes,
            },
        )
        yield span


def record_exception(span: Span, error: Exception) -> None:
    """Record an exception on the provided span."""
    span.record_exception(error)


def set_attributes(span: Span, attributes: Attributes) -> None:
    """Apply sanitized attributes to a span."""
    for key, att_value in attributes.items():
        if isinstance(att_value, bool | str | int | float):
            span.set_attribute(key, att_value)


def get_business_attributes(ctx: Any) -> Attributes:
    """Return business dimensions for the current agreement/order context."""
    attributes: Attributes = {}
    if getattr(ctx, "order", None) is not None:
        attributes["order.id"] = ctx.order.id
        return attributes
    if getattr(ctx, "agreement", None) is not None:
        attributes["agreement.id"] = ctx.agreement.id
    return attributes


def _build_event_span_name(object_type: str, object_id: str) -> str:
    """Return a human-readable root span name for AppInsights transaction views."""
    normalized_type = object_type.lower()
    if normalized_type == "order" and object_id:
        return f"Event order for {object_id}"
    if normalized_type == "agreement" and object_id:
        return f"Process agreement {object_id}"

    return f"Event {normalized_type}"
