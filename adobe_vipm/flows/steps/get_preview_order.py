from types import SimpleNamespace
from typing import override

from mpt_extension_sdk.errors.step import SkipStepError, StopStepError
from mpt_extension_sdk.pipeline import BaseStep, OrderStatusAction, OrderStatusActionType

from adobe_vipm.adobe.client import AdobeClientMixin
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.adobe.mixins.errors import AdobeCreatePreviewError
from adobe_vipm.adobe.models import AdobePreviewOrder
from adobe_vipm.flows.constants import ERR_VIPM_UNHANDLED_EXCEPTION
from adobe_vipm.flows.context import AdobeOrderContext


class GetPreviewOrder(BaseStep, AdobeClientMixin):
    """Retrieve an Adobe preview order for pricing and validation."""

    @override
    async def pre(self, ctx: AdobeOrderContext) -> None:
        if not (ctx.order.upsize_lines or ctx.order.new_lines) and not ctx.adobe_order_id:
            raise SkipStepError("No new or updated lines, skipping Adobe preview order creation.")

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        # TODO: legacy-compatible context obj for Adobe preview-order creation
        preview_order_data = SimpleNamespace(
            authorization_id=ctx.order.authorization_id,
            customer_id=ctx.order.customer_id,
            market_segment=ctx.market_segment,
            order_id=ctx.order_id,
            order=ctx.order.to_dict(),
            upsize_lines=[line.to_dict() for line in ctx.order.upsize_lines],
            new_lines=[line.to_dict() for line in ctx.order.new_lines],
            customer_data=ctx.customer_data,
            deployment_id=ctx.order.parameters.get_fulfillment_value("deploymentId"),
        )
        try:
            adobe_preview_order = self.adobe_client.create_preview_order(preview_order_data)
        except (AdobeError, AdobeCreatePreviewError) as error:
            ctx.order_state.action = OrderStatusAction(
                target_status=OrderStatusActionType.FAIL,
                message="Preview order creation failed.",
                status_notes=ERR_VIPM_UNHANDLED_EXCEPTION.to_dict(error=str(error)),
            )
            raise StopStepError("Preview order creation failed.") from error

        ctx.adobe_preview_order = AdobePreviewOrder.from_payload(adobe_preview_order)
