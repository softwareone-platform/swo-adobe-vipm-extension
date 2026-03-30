from typing import override

from mpt_extension_sdk.errors.step import SkipStepError, StopStepError
from mpt_extension_sdk.pipeline import BaseStep, OrderStatusAction, OrderStatusActionType

from adobe_vipm.adobe.client import AdobeClientMixin
from adobe_vipm.adobe.errors import AdobeAPIInvalidCustomerError
from adobe_vipm.flows.constants import ERR_CUSTOMER_LOST_EXCEPTION
from adobe_vipm.flows.context import AdobeOrderContext


class SetAdobeCustomer(BaseStep, AdobeClientMixin):
    """SetAdobeCustomer."""

    @override
    async def pre(self, ctx: AdobeOrderContext) -> None:
        if not ctx.order.customer_id:
            raise SkipStepError("No customer ID, skipping Adobe Context setup.")

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        """Populate derived state and resolve the Adobe customer when present."""
        ctx.logger.debug("Testing override the mpt_api_service is working")
        price_list = await ctx.mpt_api_service.price_list.get_by_id("PRC-5516-5707-0003")
        ctx.logger.debug("Price list: %s", price_list.id)

        try:
            ctx.adobe_customer = self.adobe_client.get_customer(
                ctx.order.authorization_id, ctx.order.customer_id
            )
        except AdobeAPIInvalidCustomerError as ex:
            ctx.logger.info(
                "Received Adobe error %s - %s, assuming lost customer "
                "and proceeding to fail the order.",
                ex.code,
                ex.message,
            )
            ctx.order_state.action = OrderStatusAction(
                target_status=OrderStatusActionType.FAIL,
                message="Failed to retrieve Adobe Customer",
                status_notes=ERR_CUSTOMER_LOST_EXCEPTION.to_dict(
                    f"Received Adobe error {ex.code} - {ex.message}"
                ),
                parameters=ctx.order.parameters.to_dict(),
            )
            raise StopStepError("Failed to retrieve Adobe Customer")
