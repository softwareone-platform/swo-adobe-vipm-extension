"""
Downsize steps of the change fulfillment flow built on Adobe partial returns.

Adobe accepts a RETURN order for any quantity up to a NEW or RENEWAL line
item's ``remainingQuantity``. Every downsize line of a Change Order is resolved
on its own: returned in full to Adobe when the returnable pool covers it, or
deferred in full to the renewal quantity when it does not.
"""

import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.fulfillment.return_submission import ReturnSubmission, plan_downsize_line
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils.returns import get_sku_returned_quantity

logger = logging.getLogger(__name__)


class PlanDownsizeReturns(Step):
    """
    Decide, per downsize line, whether its quantity is returned to Adobe or deferred.

    The returnable pool of every downsize line is read fresh from Adobe
    (``remainingQuantity`` of the NEW and RENEWAL order lines placed in the return
    window, restricted to the order's deployment). A line whose pool covers the whole
    downsize is returned in full, oldest order first; any other line is deferred in
    full to the renewal quantity. Each line is resolved on its own, so a Change Order
    may complete with lines returned and lines deferred. RETURN orders already placed
    by this MPT order (previous runs) are subtracted, so the plan only covers what is
    still outstanding and a line that was partly returned stays on the return path.
    """

    def __call__(self, client, context, next_step):
        """Plan the RETURN orders of the downsize lines."""
        adobe_client = get_adobe_client()
        context.downsize_plans = {}
        for line in context.downsize_lines:
            sku = line["item"]["externalIds"]["vendor"]
            returned_quantity = get_sku_returned_quantity(
                context.adobe_return_orders.get(sku, []), sku
            )
            plan = plan_downsize_line(adobe_client, context, line, returned_quantity)
            context.downsize_plans[sku] = plan
            logger.info(
                "%s: downsize of %s by %s resolved as %s (returned %s, allocations %s)",
                context,
                sku,
                plan.downsize_quantity,
                plan.outcome,
                plan.returned_quantity,
                [
                    (allocation.order["orderId"], allocation.quantity)
                    for allocation in plan.allocations
                ],
            )
        next_step(client, context)


class SubmitReturnAllocations(Step):
    """
    Submit the RETURN orders planned by PlanDownsizeReturns.

    Every planned allocation is first confirmed against Adobe's current
    ``remainingQuantity`` (lines whose pool shrank are re-planned before anything is
    committed). Lines whose allocation spans several source orders are submitted
    first, one RETURN order at a time, each recorded on the MPT order as soon as it
    is created. After every completed RETURN the renewal quantity of the subscription
    is lowered to ``min(currentQuantity, renewalQuantity)``, so the anniversary never
    re-provisions returned licences; the line's target quantity is only written when
    the line completes (UpdateRenewalQuantitiesDownsizes), which also applies the
    deferred lines once every return is done.

    While a RETURN is pending, or the subscription is in its renewal window, the
    order stays in Processing and the next run resumes from Adobe's state. A RETURN
    rejected because the remaining quantity dropped is re-planned once; a line
    rejected before anything of it was credited is deferred; any other rejection
    fails the order with a per-line report, keeping the returns already made.
    """

    def __call__(self, client, context, next_step):
        """Submit the planned RETURN orders."""
        if ReturnSubmission(client, get_adobe_client(), context).run():
            next_step(client, context)
