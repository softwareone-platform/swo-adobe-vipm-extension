"""
This module contains the logic to implement the change fulfillment flow.
It exposes a single function that is the entrypoint for change order
processing.
"""
import itertools
import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.constants import (
    TEMPLATE_NAME_CHANGE,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    GetReturnOrders,
    IncrementAttemptsCounter,
    SetOrUpdateCotermNextSyncDates,
    StartOrderProcessing,
    SubmitNewOrder,
    SubmitReturnOrders,
    SyncAgreement,
    UpdatePrices,
    ValidateDuplicateLines,
    ValidateRenewalWindow,
    switch_order_to_failed,
)
from adobe_vipm.flows.helpers import SetupContext
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    get_adobe_subscription_id,
    get_subscription_by_line_and_item_id,
)

logger = logging.getLogger(__name__)


class GetReturnableOrders(Step):
    """
    Compute a map of returnable orders.
    it retrieves all the NEW or RENEWAL Adobe
    placed at most 14 days ago (cancellation window) and not
    after two weeks before the anniversary date.
    The computed dictionary map a SKU to a list of ReturnableOrderInfo
    so the sum of the quantity of such list of returnable orders match the downsize
    quantity if a sum that match such quantity exists.
    """

    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        returnable_orders_count = 0
        for line in context.downsize_lines:
            sku = line["item"]["externalIds"]["vendor"]
            returnable_orders = adobe_client.get_returnable_orders_by_sku(
                context.authorization_id,
                context.adobe_customer_id,
                sku,
                context.adobe_customer["cotermDate"],
                return_orders=context.adobe_return_orders.get(sku),
            )
            returnable_orders_count += len(returnable_orders)
            returnable_by_quantity = {}
            for r in range(len(returnable_orders), 0, -1):
                for sub in itertools.combinations(returnable_orders, r):
                    returnable_by_quantity[sum([x.quantity for x in sub])] = sub

            delta = line["oldQuantity"] - line["quantity"]
            if delta not in returnable_by_quantity:
                context.adobe_returnable_orders[sku] = None
                continue

            context.adobe_returnable_orders[sku] = returnable_by_quantity[delta]
        logger.info(f"{context}: found {returnable_orders_count} returnable orders.")
        next_step(client, context)


class ValidateReturnableOrders(Step):
    """
    Validates that all the lines that should be downsized can be processed
    (the sum of the quantity of one or more orders that can be returned
    matched the downsize quantity).
    If there are SKUs that cannot be downsized and no return order
    has been placed previously, the order will be failed.
    This can happen if the draft validation have been skipped or the order
    has been switched to `Processing` if a day or more have passed after
    the draft validation.
    """

    def __call__(self, client, context, next_step):
        if context.adobe_returnable_orders and not all(
            context.adobe_returnable_orders.values()
        ) and not context.adobe_return_orders:
            non_returnable_skus = [
                k for k, v in context.adobe_returnable_orders.items() if v is None
            ]
            reason = (
                "No Adobe orders that match the desired quantity delta have been found for the "
                f"following SKUs: {', '.join(non_returnable_skus)}"
            )
            switch_order_to_failed(
                client,
                context.order,
                reason,
            )
            logger.info(f"{context}: failed due to {reason}")
            return

        next_step(client, context)


class UpdateRenewalQuantities(Step):
    """
    Updates the Adobe subscriptions renewal quantity if it doesn't match
    the agreement current quantity.
    """
    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        for line in context.downsize_lines + context.upsize_lines:
            subscription = get_subscription_by_line_and_item_id(
                context.order["subscriptions"],
                line["item"]["id"],
                line["id"],
            )
            if not subscription:
                continue
            adobe_sub_id = get_adobe_subscription_id(subscription)
            adobe_subscription = adobe_client.get_subscription(
                context.authorization_id,
                context.adobe_customer_id,
                adobe_sub_id,
            )
            qty = line["quantity"]
            old_qty = adobe_subscription["autoRenewal"]["renewalQuantity"]
            if old_qty != qty:
                adobe_client.update_subscription(
                    context.authorization_id,
                    context.adobe_customer_id,
                    adobe_sub_id,
                    quantity=qty,
                )
                logger.info(
                    f"{context}: update renewal quantity for sub "
                    f"{subscription['id']} ({adobe_sub_id}) {old_qty} -> {qty}"
                )
        next_step(client, context)


def fulfill_change_order(client, order):
    """
    Fulfills a change order by processing the necessary actions based on the provided parameters.

    Args:
        mpt_client: An instance of the MPT client used for communication with the MPT system.
        order (dict): The MPT order representing the change order to be fulfilled.

    Returns:
        None
    """
    pipeline = Pipeline(
        SetupContext(),
        IncrementAttemptsCounter(),
        ValidateDuplicateLines(),
        SetOrUpdateCotermNextSyncDates(),
        StartOrderProcessing(TEMPLATE_NAME_CHANGE),
        ValidateRenewalWindow(),
        GetReturnOrders(),
        GetReturnableOrders(),
        ValidateReturnableOrders(),
        SubmitReturnOrders(),
        SubmitNewOrder(),
        UpdateRenewalQuantities(),
        CreateOrUpdateSubscriptions(),
        UpdatePrices(),
        CompleteOrder(TEMPLATE_NAME_CHANGE),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
