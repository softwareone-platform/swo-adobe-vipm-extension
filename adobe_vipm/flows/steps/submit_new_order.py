import json
from typing import override

from mpt_extension_sdk.errors.step import DeferStepError, SkipStepError, StopStepError
from mpt_extension_sdk.pipeline import BaseStep, OrderStatusAction, OrderStatusActionType

from adobe_vipm.adobe.client import AdobeClientMixin
from adobe_vipm.adobe.constants import (
    ORDER_STATUS_DESCRIPTION,
)
from adobe_vipm.flows.constants import (
    ERR_UNEXPECTED_ADOBE_ERROR_STATUS,
    ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS,
    Param,
)
from adobe_vipm.flows.context import AdobeOrderContext


# REFACTOR: it should be renamed to CreateAdobeNewOrder
class SubmitNewOrder(BaseStep, AdobeClientMixin):
    """Create the Adobe order for the current purchase flow."""

    @override
    async def pre(self, ctx: AdobeOrderContext) -> None:
        if not (ctx.order.upsize_lines or ctx.order.new_lines):
            raise SkipStepError("No new or updated lines, skipping Adobe order creation.")

        if not ctx.adobe_new_order and not ctx.adobe_preview_order:
            raise SkipStepError("Skip creating Adobe Order, preview order was skipped.")

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        adobe_order_id = ctx.adobe_order_id
        if not ctx.adobe_order_id and ctx.adobe_preview_order:
            ctx.adobe_new_order = self.adobe_client.create_new_order(
                ctx.order.authorization_id,
                ctx.order.customer_id,
                ctx.adobe_preview_order,
                deployment_id=ctx.order.parameters.get_fulfillment_value(Param.DEPLOYMENT_ID),
            )
            adobe_order_id = ctx.adobe_new_order.id
            parameters = {
                Param.PHASE_FULFILLMENT.value: [
                    {
                        "externalId": Param.FLEXIBLE_DISCOUNTS.value,
                        "value": json.dumps(ctx.adobe_new_order.flex_discounts),
                    },
                ]
            }
            external_ids = ctx.order.external_ids.to_dict()
            external_ids["vendor"] = adobe_order_id
            await ctx.mpt_api_service.orders.update(
                ctx.order_id, externalIds=external_ids, parameters=parameters
            )

        # Refresh adobe order details even if it's just been created. First status is always
        # PENDING.
        ctx.adobe_new_order = self.adobe_client.get_order(
            ctx.order.authorization_id, ctx.order.customer_id, adobe_order_id
        )

        if ctx.adobe_new_order.is_pending:
            raise DeferStepError(f"Adobe order {adobe_order_id} is still pending")

        if ctx.adobe_new_order.is_unrecoverable:
            error_msg = ERR_UNRECOVERABLE_ADOBE_ORDER_STATUS.to_dict(
                description=ORDER_STATUS_DESCRIPTION[ctx.adobe_new_order.status]
            )
            ctx.order_state.action = OrderStatusAction(
                target_status=OrderStatusActionType.FAIL,
                message="The Adobe order is in an unrecoverable state",
                status_notes=error_msg,
            )
            raise StopStepError("The Adobe order has been failed %s", error_msg)

        if not ctx.adobe_new_order.is_processed:
            error_msg = ERR_UNEXPECTED_ADOBE_ERROR_STATUS.to_dict(status=ctx.adobe_new_order.status)
            ctx.order_state.action = OrderStatusAction(
                target_status=OrderStatusActionType.FAIL,
                message="The Adobe order is in an unexpected state",
                status_notes=error_msg,
            )
            raise StopStepError("Order has been failed due to %s", error_msg)
