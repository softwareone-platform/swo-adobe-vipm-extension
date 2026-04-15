from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, Concatenate

from mpt_extension_sdk.observability.tracing import (
    TRACER,
    get_business_attributes,
    set_attributes,
)

if TYPE_CHECKING:
    from mpt_extension_sdk.pipeline import BasePipeline, BaseStep, ExecutionContext


def start_pipeline_span[PipelineT: "BasePipeline", CtxT: "ExecutionContext", **ParamT](
    func: Callable[Concatenate[PipelineT, CtxT, ParamT], Awaitable[None]],
) -> Callable[Concatenate[PipelineT, CtxT, ParamT], Awaitable[None]]:
    """Start a child span for a pipeline execution."""

    @wraps(func)
    async def wrapper(
        self, ctx: "ExecutionContext", *args: ParamT.args, **kwargs: ParamT.kwargs
    ) -> Any:
        with TRACER.start_as_current_span(f"pipeline: {self.name}") as span:
            set_attributes(
                span,
                {
                    "mpt.extension.pipeline_name": self.name,
                    "mpt.event.id": ctx.meta.event_id,
                    "mpt.task.id": ctx.meta.task_id,
                    **get_business_attributes(ctx),
                },
            )
            return await func(self, ctx, *args, **kwargs)

    return wrapper


def start_step_span[StepT: "BaseStep", CtxT: "ExecutionContext", **ParamT](
    func: Callable[Concatenate[StepT, CtxT, ParamT], Awaitable[None]],
) -> Callable[Concatenate[StepT, CtxT, ParamT], Awaitable[None]]:
    """Start and yield a child span for a step execution."""

    @wraps(func)
    async def wrapper(self, step, ctx, *args: ParamT.args, **kwargs: ParamT.kwargs) -> Any:
        with TRACER.start_as_current_span(f"step: {step.name}") as span:
            set_attributes(
                span,
                {
                    "mpt.extension.step_name": step.name,
                    "mpt.event.id": ctx.meta.event_id,
                    "mpt.task.id": ctx.meta.task_id,
                    **get_business_attributes(ctx),
                },
            )
            return await func(self, step, ctx, *args, **kwargs)

    return wrapper
