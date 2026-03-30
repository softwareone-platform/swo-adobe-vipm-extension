from typing import override

from mpt_extension_sdk.pipeline import BaseStep

from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.context import AdobeOrderContext


class PrepareCustomerData(BaseStep):
    """Prepare Adobe customer payloads for downstream steps."""

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        """Prepare customer data for validation or fulfillment."""
        licensee = ctx.order.agreement.licensee
        new_params = {}
        updated_parameters = ctx.order.parameters
        if not ctx.order.parameters.get_ordering_value(Param.COMPANY_NAME):
            new_params[Param.COMPANY_NAME.value] = licensee.name
            updated_parameters = updated_parameters.with_ordering_value(
                Param.COMPANY_NAME, licensee.name
            )

        if not ctx.order.parameters.get_ordering_value(Param.ADDRESS):
            new_params[Param.ADDRESS.value] = licensee.address
            updated_parameters = updated_parameters.with_ordering_value(
                Param.ADDRESS, licensee.address
            )

        if not ctx.order.parameters.get_ordering_value(Param.CONTACT):
            new_params[Param.CONTACT.value] = licensee.contact
            updated_parameters = updated_parameters.with_ordering_value(
                Param.CONTACT, licensee.contact
            )

        if not new_params:
            return

        ctx.logger.info("Updating order parameters with new values: %s", new_params)
        await ctx.mpt_api_service.orders.update(
            ctx.order_id,
            parameters=updated_parameters.to_dict(),
        )
        await ctx.refresh_order()
