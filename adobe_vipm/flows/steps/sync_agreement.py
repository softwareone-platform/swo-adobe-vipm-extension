from typing import override

from mpt_extension_sdk.pipeline import BaseStep

from adobe_vipm.flows.context import AdobeOrderContext


class SyncAgreement(BaseStep):
    """Synchronize the Marketplace agreement after order completion."""

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        """Sync agreement data with the latest Adobe state."""
        ctx.logger.info("Agreement synchronization is not implemented in the SDK flow yet.")
