from typing import override

from mpt_extension_sdk.pipeline import BasePipeline, BaseStep

from adobe_vipm.flows.steps.first_step import FirstStep


class ConfigurationPipeline(BasePipeline):
    """Pipeline for configuration order fulfillment."""

    @override
    @property
    def steps(self) -> list[BaseStep]:
        return [FirstStep()]
