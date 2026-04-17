from typing import override

from mpt_extension_sdk.errors.step import SkipStepError, StopStepError
from mpt_extension_sdk.pipeline import (
    BaseStep,
    OrderStatusAction,
    OrderStatusActionType,
    refresh_order,
)

from adobe_vipm.adobe.client import AdobeClientMixin
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.adobe.models import AdobeCustomer
from adobe_vipm.flows.constants import (
    ERR_ADOBE_CONTACT,
    MARKET_SEGMENTS,
    Param,
)
from adobe_vipm.flows.context import AdobeOrderContext


class CreateAdobeCustomer(BaseStep, AdobeClientMixin):
    """Create the Adobe customer for the current purchase flow."""

    @override
    async def pre(self, ctx: AdobeOrderContext) -> None:
        if ctx.order.customer_id:
            raise SkipStepError("Adobe Customer already exists.")

        if not ctx.order.parameters.get_ordering_value(Param.CONTACT):
            ctx.order_state.action = OrderStatusAction(
                target_status=OrderStatusActionType.QUERY,
                message="Missing contact.",
                status_notes=ERR_ADOBE_CONTACT.to_dict(
                    title=Param.CONTACT, details="it is mandatory."
                ),
            )
            raise StopStepError("Missing contact.")

    @override
    @refresh_order
    async def process(self, ctx: AdobeOrderContext) -> None:
        try:
            ctx.adobe_customer = self._create_adobe_customer(ctx)
        except AdobeAPIError as error:
            ctx.order_state.action = OrderStatusAction(
                target_status=OrderStatusActionType.QUERY,
                message="Adobe API error creating customer",
                status_notes={"id": "VIPM0011", "details": error.details},
            )
            raise StopStepError("Adobe API error creating customer") from error

        status = ctx.adobe_customer.get_three_yc_commitment_request().get("status")
        if status:
            updated_parameters = ctx.order.parameters.with_fulfillment_value(
                Param.THREE_YC_COMMITMENT_REQUEST_STATUS, status
            )
            await ctx.mpt_api_service.orders.update(
                ctx.order_id, parameters=updated_parameters.to_dict()
            )

        await ctx.mpt_api_service.agreements.update(
            ctx.order.agreement_id, externalIds={"vendor": ctx.adobe_customer_id}
        )

    def _create_adobe_customer(self, ctx: AdobeOrderContext) -> AdobeCustomer:
        create_customer = (
            self.adobe_client.create_customer_account_lga
            if ctx.is_large_government_agency
            else self.adobe_client.create_customer_account
        )
        return create_customer(
            ctx.order.authorization_id,
            ctx.order.seller_id,
            ctx.order.agreement_id,
            MARKET_SEGMENTS[ctx.market_segment],
            ctx.customer_data,
        )
