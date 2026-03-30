from typing import override

from mpt_extension_sdk.pipeline import BaseStep, ExecutionContext


class FirstStep(BaseStep):
    """First step in pipeline."""

    @override
    async def process(self, ctx: ExecutionContext) -> None:
        ctx.logger.info("First step in pipeline.")
