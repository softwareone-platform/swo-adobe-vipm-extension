from typing import override

from mpt_extension_sdk.pipeline import BaseStep

from adobe_vipm.flows.constants import MPT_ORDER_STATUS_COMPLETED
from adobe_vipm.flows.context import AdobeOrderContext


class CompleteOrder(BaseStep):
    """Complete the Marketplace order with the final template."""

    def __init__(self, template_name: str) -> None:
        self._template_name = template_name

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        updated_parameters = ctx.with_due_date(None)
        template = await ctx.mpt_api_service.templates.get_template(
            product_id=ctx.order.product_id,
            status=MPT_ORDER_STATUS_COMPLETED,
            name=self._template_name,
        )
        await ctx.mpt_api_service.orders.complete(
            ctx.order_id, template.to_dict(), parameters=updated_parameters.to_dict()
        )
