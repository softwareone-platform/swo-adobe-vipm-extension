from typing import override

from mpt_extension_sdk.pipeline import BaseStep

from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.context import AdobeOrderContext


class NullifyFlexDiscountParam(BaseStep):
    """Clear flexible discount parameters after completion."""

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        """Nullify the flex discount parameter in Marketplace."""
        await ctx.mpt_api_service.agreements.update(
            ctx.order.agreement_id,
            parameters={
                Param.PHASE_FULFILLMENT: [{"externalId": Param.FLEXIBLE_DISCOUNTS, "value": None}]
            },
        )
