import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.return_submission import plan_downsize_line
from adobe_vipm.flows.fulfillment.shared import (
    SelectFlexDiscounts,
    SetOrUpdateCotermDate,
    ValidateRenewalWindow,
)
from adobe_vipm.flows.helpers import (
    SetupContext,
    UpdatePrices,
    Validate3YCCommitment,
    ValidateSkuAvailability,
)
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.validation.shared import (
    GetPreviewOrder,
    ValidateDuplicateLines,
    ValidateNoEarlyRenewal,
    ValidateNoStagedRenewal,
)

logger = logging.getLogger(__name__)


class ValidateDownsizes(Step):
    """
    Resolve the downsize lines of a draft Change Order, without blocking it.

    Adobe accepts partial returns, so every downsize is valid: a line whose returnable
    pool covers the whole downsize will be returned to Adobe, any other line will be
    deferred to the renewal quantity. The outcome is only logged here; fulfillment
    reads the pool again and its read is the authoritative one.
    """

    def __call__(self, client, context, next_step):
        """Resolve the downsize lines of a draft Change Order."""
        adobe_client = get_adobe_client()
        context.downsize_plans = {}
        for line in context.downsize_lines:
            plan = plan_downsize_line(adobe_client, context, line, returned_quantity=0)
            context.downsize_plans[plan.sku] = plan
            logger.info(
                "%s: draft downsize of %s by %s would be resolved as %s (allocations %s)",
                context,
                plan.sku,
                plan.downsize_quantity,
                plan.outcome,
                [
                    (allocation.order["orderId"], allocation.quantity)
                    for allocation in plan.allocations
                ],
            )
        next_step(client, context)


def validate_change_order(client, order):
    """Validate change order pipeline."""
    pipeline = Pipeline(
        SetupContext(),
        ValidateDuplicateLines(),
        SetOrUpdateCotermDate(),
        ValidateRenewalWindow(is_validation=True),
        ValidateNoEarlyRenewal(),
        ValidateNoStagedRenewal(),
        ValidateSkuAvailability(is_validation=True),
        ValidateDownsizes(),
        Validate3YCCommitment(is_validation=True),
        SelectFlexDiscounts(),
        GetPreviewOrder(),
        UpdatePrices(is_validation=True),
    )
    context = Context(order=order)
    pipeline.run(client, context)

    return not context.validation_succeeded, context.order
