from typing import override

from mpt_extension_sdk.errors.step import SkipStepError, StopStepError
from mpt_extension_sdk.pipeline import BaseStep, OrderStatusAction, OrderStatusActionType

from adobe_vipm.flows.constants import MARKET_SEGMENT_EDUCATION, TEMPLATE_EDUCATION_QUERY_SUBSEGMENT
from adobe_vipm.flows.context import AdobeOrderContext


class ValidateEducationSubSegments(BaseStep):
    """Validate education sub-segment requirements."""

    @override
    async def pre(self, ctx: AdobeOrderContext) -> None:
        if ctx.market_segment != MARKET_SEGMENT_EDUCATION:
            raise SkipStepError("Not an education order, skipping subsegment validation.")

    @override
    async def process(self, ctx: AdobeOrderContext) -> None:
        """Check education-specific Adobe customer data."""
        if not ctx.adobe_customer or not ctx.adobe_customer.company_profile.market_sub_segments:
            ctx.order_state.action = OrderStatusAction(
                target_status=OrderStatusActionType.QUERY,
                message="Education subsegment required.",
                parameters={"template": TEMPLATE_EDUCATION_QUERY_SUBSEGMENT},
            )
            raise StopStepError("Education subsegment required.")
