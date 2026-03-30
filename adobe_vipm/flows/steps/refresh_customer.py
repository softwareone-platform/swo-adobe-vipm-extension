from typing import override

from mpt_extension_sdk.pipeline import BaseStep

from adobe_vipm.adobe.client import AdobeClientMixin
from adobe_vipm.flows.context import AdobeOrderContext


# REVIEW
class RefreshCustomer(BaseStep, AdobeClientMixin):
    """Refresh Adobe customer data after order submission."""

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        """Reload Adobe customer information when needed."""
        ctx.adobe_customer = self.adobe_client.get_customer(
            ctx.order.authorization_id, ctx.adobe_customer_id
        )
