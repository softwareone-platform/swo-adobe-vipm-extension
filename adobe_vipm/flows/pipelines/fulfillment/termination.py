from typing import override

from mpt_extension_sdk_v6.pipeline.base import BasePipeline
from mpt_extension_sdk_v6.pipeline.step import BaseStep


class TerminationPipeline(BasePipeline):
    """Pipeline for termination order fulfillment."""

    @override
    @property
    def steps(self) -> list[BaseStep]:
        return []
