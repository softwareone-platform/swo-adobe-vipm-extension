"""
Submission of the RETURN orders of the downsize lines of a Change Order.

Adobe offers no transaction across RETURN orders, so the submission keeps the
irreversible part as small and as safe as possible:

- every planned allocation is confirmed against Adobe's current
  ``remainingQuantity`` before the first RETURN of the run, and lines whose
  pool shrank are re-planned while nothing has been committed;
- lines whose allocation spans several source orders go first (the only ones
  that can stop half-way), single-source lines next, and the renewal quantity
  of deferred lines is only reduced once every return is done;
- a RETURN rejected because the remaining quantity dropped meanwhile is
  re-planned once per line; a line rejected before anything of it was
  credited is deferred; any other rejection stops the run, leaves the returns
  already made in place and fails the order with a per-line report.
"""

import logging
from collections import defaultdict

from mpt_extension_sdk.mpt_http.mpt import update_order

from adobe_vipm.adobe.client import AdobeClient
from adobe_vipm.adobe.constants import AdobeErrorCode, AdobeOrderStatus
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeError
from adobe_vipm.flows.constants import (
    ERR_PARTIAL_RETURN_INCOMPLETE,
    ERR_RETURN_VIOLATES_3YC,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import switch_order_to_failed
from adobe_vipm.flows.sync.agreement import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils.deployment import get_deployment_id
from adobe_vipm.flows.utils.notification import notify_not_updated_subscriptions
from adobe_vipm.flows.utils.parameter import set_adobe_order_ids_created_parameter
from adobe_vipm.flows.utils.return_errors import (
    ReturnedOrders,
    ReturnErrorAction,
    build_return_report,
    classify_return_error,
)
from adobe_vipm.flows.utils.returns import DownsizeOutcome, DownsizePlan, plan_downsize
from adobe_vipm.flows.utils.subscription import get_subscription_by_line_subs_id
from adobe_vipm.notifications import send_exception

logger = logging.getLogger(__name__)


def plan_downsize_line(
    adobe_client: AdobeClient, context: Context, line: dict, returned_quantity: int
) -> DownsizePlan:
    """
    Read the returnable pool of a downsize line from Adobe and plan it.

    The pool is restricted to the order lines of the order's deployment.

    Args:
        adobe_client: Adobe API client.
        context: Order flow processing context.
        line: MPT order line with a downsize.
        returned_quantity: Quantity already returned for the line by the MPT order.

    Returns:
        The downsize plan of the line.
    """
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
        if not deployment_id or returnable_order.line.get("deploymentId") == deployment_id
    ]
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
        f"Error reconciling the renewal quantity of {plan.subscription_id}: {error}",
        [],
        context.product_id,
    )


def _get_previous_returns(context: Context) -> dict[str, ReturnedOrders]:
    return {
        sku: [
            (return_order["orderId"], line_item["quantity"])
            for return_order in return_orders
            for line_item in return_order["lineItems"]
        ]
        for sku, return_orders in context.adobe_return_orders.items()
    }


class ReturnSubmission:
    """One run of the RETURN orders of the downsize plans of an order."""

    def __init__(self, client, adobe_client: AdobeClient, context: Context):
        self.client = client
        self.adobe_client = adobe_client
        self.context = context
        self.returned = defaultdict(list, _get_previous_returns(context))
        self.replanned_skus = set()

    def run(self) -> bool:
        """
        Confirm every RETURN plan, then submit them ordered by risk.

        Returns:
            True when every RETURN plan completed and the pipeline can continue.
        """
        return_skus = [
            sku
            for sku, plan in self.context.downsize_plans.items()
            if plan.outcome == DownsizeOutcome.RETURN
        ]
        plans = [self.context.downsize_plans[sku] for sku in return_skus]
        if not all(map(self._prepare, plans)):
            return False
        ordered_plans = sorted(
            (self.context.downsize_plans[sku] for sku in return_skus),
            key=lambda plan: len(plan.allocations) <= 1,
        )
        return all(self._submit(plan) for plan in ordered_plans)

    def _prepare(self, plan: DownsizePlan) -> bool:
        pending_orders = [
            return_order["orderId"]
            for return_order in self.context.adobe_return_orders.get(plan.sku, [])
            if return_order["status"] != AdobeOrderStatus.COMPLETE
        ]
        if pending_orders:
            logger.info("%s: pending return orders %s", self.context, ", ".join(pending_orders))
            return False
        if plan.returned_quantity and not reconcile_renewal_quantity(
            self.adobe_client, self.context, plan
        ):
            return False
        is_confirmed = all(
            self.adobe_client.get_remaining_quantity(
                self.context.authorization_id,
                self.context.adobe_customer_id,
                allocation.order["orderId"],
                allocation.line["extLineItemNumber"],
            )
            >= allocation.quantity
            for allocation in plan.allocations
        )
        if not is_confirmed:
            plan = self._replan(plan)
        if plan.outcome == DownsizeOutcome.RETURN and not plan.is_fully_allocated:
            self._fail(f"the returnable orders no longer cover {plan.sku}")
            return False
        return True

    def _submit(self, plan: DownsizePlan) -> bool:
        deployment_id = get_deployment_id(self.context.order)
        for allocation in plan.allocations:
            try:
                return_order = self.adobe_client.create_return_order(
                    self.context.authorization_id,
                    self.context.adobe_customer_id,
                    allocation.order,
                    allocation.line,
                    self.context.order_id,
                    deployment_id,
                    quantity=allocation.quantity,
                )
            except AdobeError as error:
                return self._handle_failure(plan, error)
            self.context.order = set_adobe_order_ids_created_parameter(
                self.context, [return_order["orderId"]]
            )
            update_order(
                self.client, self.context.order_id, parameters=self.context.order["parameters"]
            )
            status = return_order["status"]
            if status == AdobeOrderStatus.FAILED:
                return self._handle_failure(plan, None)
            self.returned[plan.sku].append((return_order["orderId"], allocation.quantity))
            if status != AdobeOrderStatus.COMPLETE:
                logger.info("%s: return order %s is pending", self.context, return_order["orderId"])
                return False
            if not reconcile_renewal_quantity(self.adobe_client, self.context, plan):
                return False
        return True

    def _handle_failure(self, plan: DownsizePlan, error: AdobeError | None) -> bool:
        is_line_credited = bool(self.returned.get(plan.sku))
        action = classify_return_error(
            error,
            is_line_credited=is_line_credited,
            can_replan=plan.sku not in self.replanned_skus,
        )
        logger.warning("%s: return of %s failed (%s): %s", self.context, plan.sku, action, error)
        if action == ReturnErrorAction.RETRY:
            order_id = self.context.order_id
            title = f"Error creating return order {order_id}"
            send_exception(title=title, text=str(error))
            raise error
        if action == ReturnErrorAction.REPLAN:
            replanned = self._replan(plan)
            if replanned.outcome == DownsizeOutcome.DEFER or replanned.is_fully_allocated:
                return self._submit(replanned)
            action = ReturnErrorAction.FAIL if is_line_credited else ReturnErrorAction.DEFER
        if action == ReturnErrorAction.DEFER:
            logger.info("%s: %s cannot be returned, deferring it", self.context, plan.sku)
            self.context.downsize_plans[plan.sku] = plan.as_deferred()
            return True
        self._fail(str(error or "a return order failed on Adobe"), error)
        return False

    def _replan(self, plan: DownsizePlan) -> DownsizePlan:
        self.replanned_skus.add(plan.sku)
        line = next(
            line
            for line in self.context.downsize_lines
            if line["item"]["externalIds"]["vendor"] == plan.sku
        )
        returned_orders = self.returned.get(plan.sku, [])
        returned_quantity = sum(quantity for _, quantity in returned_orders)
        replanned = plan_downsize_line(self.adobe_client, self.context, line, returned_quantity)
        logger.info("%s: %s re-planned as %s", self.context, plan.sku, replanned.outcome)
        self.context.downsize_plans[plan.sku] = replanned
        return replanned

    def _fail(self, reason: str, error: AdobeError | None = None) -> None:
        is_credited = any(self.returned.values())
        if (
            not is_credited
            and getattr(error, "code", None) == AdobeErrorCode.RETURN_VIOLATES_3YC_MCQ
        ):
            failure = ERR_RETURN_VIOLATES_3YC.to_dict(error=reason)
        else:
            failure = ERR_PARTIAL_RETURN_INCOMPLETE.to_dict(
                details=build_return_report(self.context.downsize_plans, self.returned),
                error=reason,
            )
        switch_order_to_failed(self.client, self.context.order, failure)
        logger.info("%s: failed due to %s", self.context, failure["message"])
        if is_credited:
            order_id = self.context.order_id
            title = f"Downsize partially returned {order_id}"
            send_exception(title=title, text=failure["message"])
            _sync_agreement(self.client, self.adobe_client, self.context)


def _sync_agreement(client, adobe_client, context):
    try:
        sync_agreements_by_agreement_ids(
            client, adobe_client, [context.agreement_id], dry_run=False, sync_prices=False
        )
    except Exception:
        logger.exception("%s: agreement sync after a failed downsize failed", context)
