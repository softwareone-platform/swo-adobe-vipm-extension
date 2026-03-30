from typing import override

from mpt_extension_sdk.errors.step import SkipStepError
from mpt_extension_sdk.pipeline import BaseStep

from adobe_vipm.adobe.client import AdobeClientMixin
from adobe_vipm.flows.context import AdobeOrderContext


class Validate3YCCommitment(BaseStep, AdobeClientMixin):
    """Validate 3YC commitment constraints."""

    @override
    async def pre(self, ctx: AdobeOrderContext) -> None:
        # TODO: think about add a decorator to inject / fetch the adobe_orders
        ctx.adobe_return_orders = self.adobe_client.get_orders(
            ctx.order.authorization_id, ctx.order.customer_id, ctx.order_id
        )
        if ctx.adobe_return_orders:
            raise SkipStepError("Adobe return order, skipping 3YC validation.")

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        """Validate 3YC commitment data before submitting the order."""
        raise SkipStepError("Pending to implement")
