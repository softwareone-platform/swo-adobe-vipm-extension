from abc import ABC, abstractmethod

from mpt_extension_sdk_v6.pipeline.context import ExecutionContext


class BaseStep(ABC):
    """Base step class for pipeline execution."""

    async def run(self, ctx: ExecutionContext) -> None:
        """Execute full step lifecycle."""
        await self.pre(ctx)
        await self.process(ctx)
        await self.post(ctx)

    async def pre(self, ctx: ExecutionContext) -> None:
        """Run pre-processing hook."""

    @abstractmethod
    async def process(self, ctx: ExecutionContext) -> None:
        """Run business processing."""
        raise NotImplementedError

    async def post(self, ctx: ExecutionContext) -> None:
        """Run post-processing hook."""
