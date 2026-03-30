from typing import override

from mpt_extension_sdk.pipeline import BaseStep

from adobe_vipm.flows.constants import MPT_ORDER_STATUS_PROCESSING
from adobe_vipm.flows.context import AdobeOrderContext


class StartOrderProcessing(BaseStep):
    """Resolve the processing template for the current order."""

    def __init__(self, template_name: str) -> None:
        self._template_name = template_name

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        """Load the template and update the order when it changes."""
        template = await ctx.mpt_api_service.templates.get_template(
            product_id=ctx.order.product_id,
            status=MPT_ORDER_STATUS_PROCESSING,
            name=self._template_name,
        )
        current_template = ctx.order.template
        if template and (current_template is None or template.id != current_template.id):
            await ctx.mpt_api_service.templates.set_order_template(ctx.order_id, template)
            ctx.logger.info("Template updated to %s", template.name)

    @override
    async def post(self, ctx: AdobeOrderContext) -> None:
        if not ctx.due_date:
            # TODO: this should be a notification:
            #  await ctx.mpt_api_service.notifications.notify(...)
            ctx.logger.info("No due date set, skipping notification.")
