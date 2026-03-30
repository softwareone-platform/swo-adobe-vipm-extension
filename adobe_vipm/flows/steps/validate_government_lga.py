from typing import override

from mpt_extension_sdk.errors.step import SkipStepError, StopStepError
from mpt_extension_sdk.pipeline import BaseStep, OrderStatusAction, OrderStatusActionType

from adobe_vipm.flows.constants import ERR_ADOBE_AGENCY_TYPE, VALID_GOVERNMENT_AGENCY_TYPES, Param
from adobe_vipm.flows.context import AdobeOrderContext


class ValidateGovernmentLGA(BaseStep):
    """Validate government-specific ordering constraints."""

    @override
    async def pre(self, ctx: AdobeOrderContext) -> None:
        if not ctx.is_large_government_agency:
            raise SkipStepError("Not a large government agency, skipping LGA validation.")

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        """Validate LGA requirements for the current order."""
        agency_type = ctx.order.parameters.get_ordering_value(Param.AGENCY_TYPE)
        if agency_type not in VALID_GOVERNMENT_AGENCY_TYPES:
            ctx.order_state.action = OrderStatusAction(
                target_status=OrderStatusActionType.QUERY,
                message="Agency type is not valid for segment",
                status_notes=ERR_ADOBE_AGENCY_TYPE.to_dict(
                    title=Param.AGENCY_TYPE.value,
                    details="This parameter is mandatory and must be: FEDERAL, STATE.",
                ),
                parameters=ctx.order.parameters.get_ordering_value(Param.AGENCY_TYPE),
            )
            raise StopStepError("Agency type is not valid for segment %s", ctx.market_segment)
