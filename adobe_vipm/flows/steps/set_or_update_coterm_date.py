import datetime as dt
from typing import override

from mpt_extension_sdk.errors.step import SkipStepError
from mpt_extension_sdk.pipeline import BaseStep

from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.context import AdobeOrderContext


class SetOrUpdateCotermDate(BaseStep):
    """Set or update coterm-related parameters after fulfillment."""

    @override
    async def pre(self, ctx: AdobeOrderContext) -> None:
        if not ctx.adobe_customer or not ctx.adobe_customer.coterm_date:
            raise SkipStepError("No coterm date, skipping coterm date update.")

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        adobe_coterm_date = dt.datetime.fromisoformat(ctx.adobe_customer.coterm_date).date()
        order_coterm_date = ctx.order.parameters.get_fulfillment_value(Param.COTERM_DATE)
        parameters_to_update = {}
        if adobe_coterm_date.isoformat() == order_coterm_date:
            parameters_to_update[Param.COTERM_DATE] = adobe_coterm_date.isoformat()

        commitment = (
            ctx.adobe_customer.get_three_yc_commitment_request()
            or ctx.adobe_customer.three_yc_commitment
        )
        if commitment:
            parameters_to_update[Param.THREE_YC_ENROLL_STATUS] = commitment.get("status")
            parameters_to_update[Param.THREE_YC_COMMITMENT_REQUEST_STATUS] = None
            parameters_to_update[Param.THREE_YC_START_DATE] = commitment.get("startDate")
            parameters_to_update[Param.THREE_YC_END_DATE] = commitment.get("endDate")
            parameters_to_update[Param.THREE_YC] = None

        await ctx.mpt_api_service.orders.update(ctx.order_id, parameters=parameters_to_update)
