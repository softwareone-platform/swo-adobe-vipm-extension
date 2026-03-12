from typing import override

from mpt_extension_sdk_v6.pipeline.context import ExecutionContext
from mpt_extension_sdk_v6.pipeline.step import BaseStep


class FirstStep(BaseStep):
    """First step in pipeline."""

    @override
    async def process(self, ctx: ExecutionContext) -> None:
        ctx.logger.info("First step in pipeline.")
        ctx.logger.info(ctx)
