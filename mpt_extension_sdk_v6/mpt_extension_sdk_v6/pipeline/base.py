from abc import ABC, abstractmethod

from mpt_extension_sdk_v6.errors.pipeline import CancelError, DeferError
from mpt_extension_sdk_v6.errors.step import (
    DeferStepError,
    SkipStepError,
    StopStepError,
)
from mpt_extension_sdk_v6.observability.tracing import (
    start_pipeline_span,
    start_step_span,
)
from mpt_extension_sdk_v6.pipeline.context import ExecutionContext
from mpt_extension_sdk_v6.pipeline.step import BaseStep


class BasePipeline(ABC):
    """Sequential pipeline executor."""

    @property
    @abstractmethod
    def steps(self) -> list[BaseStep]:
        """Pipeline steps."""
        raise NotImplementedError

    async def execute(self, ctx: ExecutionContext) -> None:
        """Execute pipeline steps sequentially."""
        with start_pipeline_span(self, ctx):
            ctx.logger.info("Starting pipeline %s", self.__class__.__name__)
            for step in self.steps:
                await self._execute_step(step, ctx)

    async def _execute_step(self, step: BaseStep, ctx: ExecutionContext) -> None:
        """Execute a single step inside its tracing span."""
        ctx.logger.info("Running step %s", step.__class__.__name__)
        with start_step_span(step, ctx) as step_span:
            try:
                await step.run(ctx)
            except DeferStepError as error:
                self._handle_step_error(ctx, step_span, "deferred", error)
                raise DeferError(str(error), delay_seconds=error.delay_seconds) from error
            except SkipStepError as error:
                self._handle_step_error(ctx, step_span, "skipped", error)
            except StopStepError as error:
                self._handle_step_error(ctx, step_span, "stopped", error)
                raise CancelError(str(error)) from error
            except Exception as error:
                self._handle_step_error(ctx, step_span, "failed", error)
                raise
            else:
                ctx.logger.info("Step %s completed", step.__class__.__name__)

    @staticmethod
    def _handle_step_error(
        ctx: ExecutionContext,
        step_span: object,
        outcome: str,
        error: Exception,
    ) -> None:
        """Record tracing and logging details for a step failure mode."""
        ctx.logger.info("Step %s - reason: %s", outcome, error)
