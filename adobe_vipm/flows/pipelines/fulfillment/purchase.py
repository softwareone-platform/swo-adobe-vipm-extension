from typing import override

from mpt_extension_sdk_v6.pipeline.base import BasePipeline
from mpt_extension_sdk_v6.pipeline.step import BaseStep

from adobe_vipm.flows.steps.first_step import FirstStep


class PurchasePipeline(BasePipeline):
    """Pipeline for purchase order fulfillment."""

    @override
    @property
    def steps(self) -> list[BaseStep]:
        return [FirstStep()]
