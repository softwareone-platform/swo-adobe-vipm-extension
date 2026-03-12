from abc import ABC, abstractmethod

from mpt_extension_sdk_v6.errors.pipeline import CancelError, DeferError
from mpt_extension_sdk_v6.errors.step import DeferStepError, SkipStepError, StopStepError
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
        ctx.logger.info("Starting pipeline %s", self.__class__.__name__)
        for step in self.steps:
            step_name = step.__class__.__name__
            ctx.logger.info("Running step %s", step_name)
            try:
                await step.run(ctx)
            except DeferStepError as error:
                ctx.logger.info("Step deferred - reason: %s", error)
                raise DeferError(str(error), delay_seconds=error.delay_seconds) from error
            except SkipStepError as error:
                ctx.logger.info("Step skipped - reason: %s", error)
                continue
            except StopStepError as error:
                ctx.logger.info("Step stopped - reason: %s", error)
                raise CancelError(str(error)) from error
            else:
                ctx.logger.info("Step %s completed", step.__class__.__name__)
