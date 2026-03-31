from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Span, Status, StatusCode

_TRACER = trace.get_tracer("mpt_extension_sdk_v6")
type AttributeValue = str | int | float | bool
type Attributes = dict[str, AttributeValue]


@contextmanager
def start_event_span(
    path: str,
    *,
    task_based: bool,
    event: Any,
) -> Iterator[Span]:
    """Start and yield the root span for an incoming event delivery."""
    event_type = getattr(getattr(event, "details", None), "event_type", "")
    span_name = f"{path}:{event_type or 'event'}"
    with _TRACER.start_as_current_span(span_name, context=Context()) as span:
        set_attributes(
            span,
            {
                "mpt.extension.route_path": path,
                "mpt.extension.task_based": task_based,
                "mpt.event.id": getattr(event, "id", ""),
                "mpt.event.type": event_type,
                "mpt.object.id": getattr(getattr(event, "object", None), "id", ""),
                "mpt.object.type": getattr(getattr(event, "object", None), "object_type", ""),
                "mpt.task.id": getattr(getattr(event, "task", None), "id", ""),
            },
        )
        yield span


@contextmanager
def start_pipeline_span(pipeline: Any, ctx: Any) -> Iterator[Span]:
    """Start and yield a child span for a pipeline execution."""
    pipeline_name = pipeline.__class__.__name__
    with _TRACER.start_as_current_span(f"pipeline:{pipeline_name}") as span:
        set_attributes(
            span,
            {
                "mpt.extension.pipeline_name": pipeline_name,
                "mpt.object.id": ctx.meta.object_id,
                "mpt.object.type": ctx.meta.object_type,
                "mpt.event.id": ctx.meta.event_id,
                "mpt.task.id": ctx.meta.task_id,
            },
        )
        yield span


@contextmanager
def start_step_span(step: Any, ctx: Any) -> Iterator[Span]:
    """Start and yield a child span for a step execution."""
    step_name = step.__class__.__name__
    with _TRACER.start_as_current_span(f"step:{step_name}") as span:
        set_attributes(
            span,
            {
                "mpt.extension.step_name": step_name,
                "mpt.object.id": ctx.meta.object_id,
                "mpt.object.type": ctx.meta.object_type,
                "mpt.event.id": ctx.meta.event_id,
                "mpt.task.id": ctx.meta.task_id,
            },
        )
        yield span


def record_exception(span: Span, error: Exception) -> None:
    """Record an exception on the provided span."""
    span.record_exception(error)


def set_attributes(span: Span, attributes: Attributes) -> None:
    """Apply sanitized attributes to a span."""
    for key, value in attributes.items():
        if isinstance(value, bool | str | int | float):
            span.set_attribute(key, value)
