"""
Downsize steps of the change fulfillment flow built on Adobe partial returns.

Adobe accepts a RETURN order for any quantity up to a NEW or RENEWAL line
item's ``remainingQuantity``. Every downsize line of a Change Order is resolved
on its own: returned in full to Adobe when the returnable pool covers it, or
deferred in full to the renewal quantity when it does not.
"""

import logging

from mpt_extension_sdk.mpt_http.mpt import update_order

from adobe_vipm.adobe.client import AdobeClient, get_adobe_client
from adobe_vipm.adobe.constants import AdobeErrorCode, AdobeOrderStatus
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import ERR_NO_RETURABLE_ERRORS_FOUND, Param
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import switch_order_to_failed
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils.deployment import get_deployment_id
from adobe_vipm.flows.utils.notification import notify_not_updated_subscriptions
from adobe_vipm.flows.utils.parameter import set_adobe_order_ids_created_parameter
from adobe_vipm.flows.utils.returns import (
    DownsizeOutcome,
    DownsizePlan,
    get_sku_returned_quantity,
    plan_downsize,
)
from adobe_vipm.flows.utils.subscription import get_subscription_by_line_subs_id
from adobe_vipm.notifications import send_exception

logger = logging.getLogger(__name__)


def _is_deployment_line(line_item: dict, deployment_id: str | None) -> bool:
    return deployment_id == line_item.get("deploymentId") if deployment_id else True


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
            plan = self._plan_line(adobe_client, context, line)
            context.downsize_plans[plan.sku] = plan
            logger.info(
                "%s: downsize of %s by %s resolved as %s (returned %s, allocations %s)",
                context,
                plan.sku,
                plan.downsize_quantity,
                plan.outcome,
                plan.returned_quantity,
                [
                    (allocation.order["orderId"], allocation.quantity)
                    for allocation in plan.allocations
                ],
            )
        next_step(client, context)

    def _plan_line(self, adobe_client, context, line):
        sku = line["item"]["externalIds"]["vendor"]
        subscription_id = get_subscription_by_line_subs_id(
            context.order["agreement"]["subscriptions"], line
        )
        deployment_id = get_deployment_id(context.order)
        pool = [
            returnable_order
            for returnable_order in adobe_client.get_returnable_orders_by_subscription_id(
                context.authorization_id,
                context.adobe_customer_id,
                subscription_id,
                context.adobe_customer["cotermDate"],
            )
            if _is_deployment_line(returnable_order.line, deployment_id)
        ]
        returned_quantity = get_sku_returned_quantity(context.adobe_return_orders.get(sku, []), sku)
        return plan_downsize(line, subscription_id, pool, returned_quantity)


def reconcile_renewal_quantity(
    adobe_client: AdobeClient, context: Context, plan: DownsizePlan
) -> bool:
    """
    Lower the renewal quantity of a plan's subscription to the licences it holds.

    Writes ``min(currentQuantity, renewalQuantity)`` when it differs from the current
    renewal quantity, keeping the auto-renewal flag as it is. A subscription in its
    renewal window (Adobe error 3120) is retried on the next run; any other Adobe
    error is notified. The returns already placed are never undone.

    Args:
        adobe_client: Adobe API client.
        context: Order flow processing context.
        plan: RETURN plan of the downsize line.

    Returns:
        False when the renewal quantity could not be written and the pipeline must stop.
    """
    subscription = adobe_client.get_subscription(
        context.authorization_id, context.adobe_customer_id, plan.subscription_id
    )
    current_quantity = subscription[Param.CURRENT_QUANTITY.value]
    renewal_quantity = subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]
    if current_quantity >= renewal_quantity:
        return True
    try:
        adobe_client.update_subscription(
            context.authorization_id,
            context.adobe_customer_id,
            plan.subscription_id,
            auto_renewal=subscription["autoRenewal"]["enabled"],
            quantity=current_quantity,
        )
    except AdobeAPIError as error:
        _handle_reconcile_error(context, plan, error)
        return False
    logger.info(
        "%s: renewal quantity of %s reconciled %s -> %s",
        context,
        plan.subscription_id,
        renewal_quantity,
        current_quantity,
    )
    return True


def _handle_reconcile_error(context, plan, error):
    if error.code == AdobeErrorCode.INVALID_RENEWAL_STATE:
        logger.info(
            "%s: subscription %s is in its renewal window, renewal quantity "
            "reconciliation will be retried",
            context,
            plan.subscription_id,
        )
        return
    logger.error(
        "%s: failed to reconcile the renewal quantity of %s",
        context,
        plan.subscription_id,
    )
    notify_not_updated_subscriptions(
        context.order_id,
        f"Error reconciling the renewal quantity of subscription {plan.subscription_id} "
        f"after a return, {error}",
        [],
        context.product_id,
    )


class SubmitReturnAllocations(Step):
    """
    Submit the RETURN orders planned by PlanDownsizeReturns, one at a time.

    Each allocation becomes a RETURN order for its allocated quantity against its
    source order, recorded on the MPT order as soon as it is created. While a RETURN
    order of a line is pending on Adobe's side the pipeline stops and the MPT order
    stays in Processing; the next run plans again from Adobe's state, so a retry
    never re-submits or over-returns. A line that was partly returned and can no
    longer be covered by its pool fails the order.

    After every completed RETURN order the renewal quantity of the subscription is
    reconciled to ``min(currentQuantity, renewalQuantity)``: Adobe keeps an explicit
    renewal quantity unchanged by returns, so without it the anniversary would
    re-provision returned licences. The value never exceeds the licences held and
    never raises an earlier deferred reduction; the line's target quantity is only
    written once the line completes (UpdateRenewalQuantitiesDownsizes). The
    reconciliation is idempotent and also runs before submitting the next RETURN of
    a line already partly returned, which recovers a run interrupted between a
    RETURN and its reconciliation.
    """

    def __call__(self, client, context, next_step):
        """Submit the planned RETURN orders."""
        adobe_client = get_adobe_client()
        return_plans = [
            plan
            for plan in context.downsize_plans.values()
            if plan.outcome == DownsizeOutcome.RETURN
        ]
        for plan in return_plans:
            if not self._submit_plan(client, adobe_client, context, plan):
                return
        next_step(client, context)

    def _submit_plan(self, client, adobe_client, context, plan):
        """Submit the RETURN orders of a plan; False when the pipeline must stop."""
        return self._is_ready(client, adobe_client, context, plan) and self._submit_allocations(
            client, adobe_client, context, plan
        )

    def _is_ready(self, client, adobe_client, context, plan):
        if self._has_pending_return_orders(context, plan.sku):
            return False
        if plan.returned_quantity and not reconcile_renewal_quantity(adobe_client, context, plan):
            return False
        if not plan.is_fully_allocated:
            self._fail_not_covered(client, context, plan.sku)
            return False
        return True

    def _submit_allocations(self, client, adobe_client, context, plan):
        deployment_id = get_deployment_id(context.order)
        for allocation in plan.allocations:
            return_order = self._submit_return_order(
                client, adobe_client, context, allocation, deployment_id
            )
            if return_order["status"] != AdobeOrderStatus.COMPLETE:
                logger.info(
                    "%s: return order %s for %s is pending",
                    context,
                    return_order["orderId"],
                    plan.sku,
                )
                return False
            if not reconcile_renewal_quantity(adobe_client, context, plan):
                return False
        return True

    def _has_pending_return_orders(self, context, sku):
        pending_orders = [
            return_order["orderId"]
            for return_order in context.adobe_return_orders.get(sku, [])
            if return_order["status"] != AdobeOrderStatus.COMPLETE
        ]
        if pending_orders:
            logger.info(
                "%s: there are pending return orders %s for %s",
                context,
                ", ".join(pending_orders),
                sku,
            )
        return bool(pending_orders)

    def _fail_not_covered(self, client, context, sku):
        error = ERR_NO_RETURABLE_ERRORS_FOUND.to_dict(non_returnable_skus=sku)
        switch_order_to_failed(client, context.order, error)
        logger.info("%s: failed due to %s", context, error["message"])

    def _submit_return_order(self, client, adobe_client, context, allocation, deployment_id):
        try:
            return_order = adobe_client.create_return_order(
                context.authorization_id,
                context.adobe_customer_id,
                allocation.order,
                allocation.line,
                context.order_id,
                deployment_id,
                quantity=allocation.quantity,
            )
        except AdobeAPIError as error:
            logger.warning("%s", error)
            send_exception(title=f"Error creating return order {context.order_id}", text=str(error))
            raise
        logger.info(
            "%s: return order %s created for %s of order %s",
            context,
            return_order["orderId"],
            allocation.quantity,
            allocation.order["orderId"],
        )
        context.order = set_adobe_order_ids_created_parameter(context, [return_order["orderId"]])
        update_order(client, context.order_id, parameters=context.order["parameters"])
        return return_order
