from typing import override

from mpt_extension_sdk.errors.step import SkipStepError
from mpt_extension_sdk.pipeline import BaseStep

from adobe_vipm.flows.constants import AGREEMENT_VISIBLE_PARAMETERS, Param
from adobe_vipm.flows.context import AdobeOrderContext


class UpdateAgreementParamsVisibility(BaseStep):
    """Update Marketplace agreement parameter visibility."""

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        """Adjust visibility flags for agreement parameters."""
        agreement_type = ctx.order.parameters.get_ordering_value(Param.AGREEMENT_TYPE)
        if not agreement_type:
            raise SkipStepError("No agreement type.")

        visible_params = list(AGREEMENT_VISIBLE_PARAMETERS.get(agreement_type, []))
        visible_params.extend(AGREEMENT_VISIBLE_PARAMETERS.get(ctx.market_segment, []))
        updated_parameters = ctx.order.parameters.with_visibility(visible_params)

        await ctx.mpt_api_service.orders.update(
            ctx.order_id, parameters=updated_parameters.to_dict()
        )
