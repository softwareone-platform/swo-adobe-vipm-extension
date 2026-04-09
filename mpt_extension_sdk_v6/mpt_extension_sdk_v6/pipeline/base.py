from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from mpt_extension_sdk_v6.errors.pipeline import CancelError, DeferError
from mpt_extension_sdk_v6.errors.step import DeferStepError, SkipStepError, StopStepError
from mpt_extension_sdk_v6.observability.decorators import start_pipeline_span, start_step_span

if TYPE_CHECKING:
    from mpt_extension_sdk_v6.pipeline import BaseStep, ExecutionContext


class BasePipeline(ABC):
    """Sequential pipeline executor."""

    @property
    def name(self) -> str:
        """Pipeline name."""
        return self.__class__.__name__

    @property
    @abstractmethod
    def steps(self) -> list["BaseStep"]:
        """Pipeline steps."""
        raise NotImplementedError

    @start_pipeline_span
    async def execute(self, ctx: "ExecutionContext") -> None:
        """Execute pipeline steps sequentially."""
        ctx.logger.info("Starting pipeline %s", self.name)
        for step in self.steps:
            await self._execute_step(step, ctx)  # noqa: WPS476

    async def on_step_deferred(
        self, step: "BaseStep", ctx: "ExecutionContext", error: DeferStepError
    ) -> None:
        """Handle a deferred step outcome."""
        ctx.logger.info("Step %s deferred - reason: %s", step.name, error)

    async def on_step_failed(
        self, step: "BaseStep", ctx: "ExecutionContext", error: Exception
    ) -> None:
        """Handle an unexpected step exception."""
        ctx.logger.error("Step %s - unhandled exception", step.name, exc_info=error)

    async def on_step_skipped(
        self, step: "BaseStep", ctx: "ExecutionContext", error: SkipStepError
    ) -> None:
        """Handle a skipped step outcome."""
        ctx.logger.info("Step %s skipped - reason: %s", step.name, error)

    async def on_step_stopped(
        self, step: "BaseStep", ctx: "ExecutionContext", error: StopStepError
    ) -> None:
        """Handle a stopped step outcome."""
        ctx.logger.info("Step %s stopped - reason: %s", step.name, error)

    async def on_step_succeeded(self, step: "BaseStep", ctx: "ExecutionContext") -> None:
        """Handle a successful step outcome."""
        ctx.logger.info("Step %s completed", step.name)

    @start_step_span
    async def _execute_step(self, step: "BaseStep", ctx: "ExecutionContext") -> None:
        """Execute a single step inside its tracing span."""
        ctx.logger.info("Running step %s", step.name)
        try:
            await step.run(ctx)
        except DeferStepError as error:
            await self.on_step_deferred(step, ctx, error)
            raise DeferError(str(error), delay_seconds=error.delay_seconds)
        except SkipStepError as error:
            await self.on_step_skipped(step, ctx, error)
        except StopStepError as error:
            await self.on_step_stopped(step, ctx, error)
            raise CancelError(str(error))
        except Exception as error:
            await self.on_step_failed(step, ctx, error)
            raise
        else:
            await self.on_step_succeeded(step, ctx)
