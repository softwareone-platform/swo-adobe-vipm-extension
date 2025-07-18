"""
This module contains the logic to implement the change fulfillment flow.
It exposes a single function that is the entrypoint for change order
processing.
"""

import itertools
import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_INVALID_RENEWAL_STATE,
    ERR_NO_RETURABLE_ERRORS_FOUND,
    TEMPLATE_NAME_CHANGE,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    GetReturnOrders,
    SetOrUpdateCotermDate,
    SetupDueDate,
    StartOrderProcessing,
    SubmitNewOrder,
    SubmitReturnOrders,
    SyncAgreement,
    ValidateDuplicateLines,
    ValidateRenewalWindow,
    switch_order_to_failed,
)
from adobe_vipm.flows.helpers import (
    SetupContext,
    UpdatePrices,
    Validate3YCCommitment,
)
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    get_adobe_subscription_id,
    get_subscription_by_line_and_item_id,
    notify_not_updated_subscriptions,
)
from adobe_vipm.flows.utils.customer import is_within_coterm_window

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
        if is_within_coterm_window(context.adobe_customer):
            logger.info(
                "Downsize occurs in the last two weeks before the anniversary date. "
                "Returnable orders are not going to be submitted, the renewal quantity "
                "will be updated."
            )
            next_step(client, context)
            return

        for line in context.downsize_lines:
            sku = line["item"]["externalIds"]["vendor"]
            returnable_orders = adobe_client.get_returnable_orders_by_sku(
                context.authorization_id,
                context.adobe_customer_id,
                sku,
                context.adobe_customer["cotermDate"],
                return_orders=context.adobe_return_orders.get(sku),
            )
            if not returnable_orders:
                logger.info(f"{context}: no returnable orders found for sku {sku}")
                continue
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
        if (
            context.adobe_returnable_orders
            and not all(context.adobe_returnable_orders.values())
            and not context.adobe_return_orders
        ):
            non_returnable_skus = [
                k for k, v in context.adobe_returnable_orders.items() if v is None
            ]
            error = ERR_NO_RETURABLE_ERRORS_FOUND.to_dict(
                non_returnable_skus=", ".join(non_returnable_skus),
            )

            switch_order_to_failed(
                client,
                context.order,
                error,
            )
            logger.info(f"{context}: failed due to {error['message']}")
            return

        next_step(client, context)


class UpdateRenewalQuantities(Step):
    """
    Updates the Adobe subscriptions renewal quantity if it doesn't match
    the agreement current quantity.
    If process_downsize_lines is False, the downsize lines will not be processed.
    If process_upsize_lines is False, the upsize and new lines will not be processed.
    The upsizes and new lines are processed first, to process correctly the 3yc
    to maintain the compliant with the 3yc minimum quantities.
    """

    def __init__(self):
        self.error = None

    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        context.updated = []
        self._update_lines(adobe_client, context)
        if self.error:
            self._handle_subscription_update_error(adobe_client, client, context, self.error)
            return

        next_step(client, context)

    def _get_lines(self, context):
        return context.upsize_lines + context.new_lines

    def _update_lines(self, adobe_client, context):
        for line in self._get_lines(context):
            self._update_line(adobe_client, context, line)

    def _update_line(self, adobe_client, context, line):
        subscription = get_subscription_by_line_and_item_id(
            context.order["subscriptions"],
            line["item"]["id"],
            line["id"],
        )
        if not subscription:
            return
        adobe_sub_id = get_adobe_subscription_id(subscription)
        adobe_subscription = adobe_client.get_subscription(
            context.authorization_id,
            context.adobe_customer_id,
            adobe_sub_id,
        )
        qty = line["quantity"]
        old_qty = adobe_subscription["autoRenewal"]["renewalQuantity"]

        if old_qty != qty:
            try:
                adobe_client.update_subscription(
                    context.authorization_id,
                    context.adobe_customer_id,
                    adobe_sub_id,
                    quantity=qty,
                )
            except AdobeAPIError as e:
                if not (
                    e.code == AdobeStatus.LINE_ITEM_OFFER_ID_EXPIRED and context.adobe_new_order
                ):
                    logger.error(
                        f"{context}: failed to update renewal quantity for "
                        f"{subscription['id']} ({adobe_sub_id}) due to {e}"
                    )
                    notify_not_updated_subscriptions(
                        context.order["id"],
                        f"Error updating subscription {subscription['id']}, {str(e)}",
                        [],
                        context.product_id,
                    )
                    self.error = e
                    return

            logger.info(
                f"{context}: update renewal quantity for sub "
                f"{subscription['id']} ({adobe_sub_id}) {old_qty} -> {qty}"
            )
            context.updated.append(
                {
                    "subscription_vendor_id": adobe_sub_id,
                    "old_quantity": old_qty,
                    "new_quantity": qty,
                }
            )

    def _handle_subscription_update_error(self, adobe_client, client, context, e):
        self._rollback_updated_subscriptions(adobe_client, context)
        if e.code in [
            AdobeStatus.INVALID_RENEWAL_STATE,
            AdobeStatus.SUBSCRIPTION_INACTIVE,
        ]:
            switch_order_to_failed(
                client,
                context.order,
                ERR_INVALID_RENEWAL_STATE.to_dict(error=e.message),
            )

    def _rollback_updated_subscriptions(self, adobe_client, context):
        try:
            for updated in context.updated:
                adobe_client.update_subscription(
                    context.authorization_id,
                    context.adobe_customer_id,
                    updated["subscription_vendor_id"],
                    quantity=updated["old_quantity"],
                )
            if context.adobe_new_order:
                adobe_client.create_return_order_by_adobe_order(
                    context.authorization_id,
                    context.adobe_customer_id,
                    context.adobe_new_order,
                )
        except Exception as e:
            notify_not_updated_subscriptions(
                context.order["id"],
                f"Error rolling back updated subscriptions: {e}",
                context.updated,
                context.product_id,
            )
            logger.error(f"Error rolling back updated subscriptions: {e}")


class UpdateRenewalQuantitiesDownsizes(UpdateRenewalQuantities):
    def _get_lines(self, context):
        return context.downsize_lines


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
        SetupDueDate(),
        ValidateDuplicateLines(),
        SetOrUpdateCotermDate(),
        StartOrderProcessing(TEMPLATE_NAME_CHANGE),
        ValidateRenewalWindow(),
        GetReturnOrders(),
        GetReturnableOrders(),
        ValidateReturnableOrders(),
        Validate3YCCommitment(),
        GetPreviewOrder(),
        SubmitNewOrder(),
        UpdateRenewalQuantities(),
        SubmitReturnOrders(),
        UpdateRenewalQuantitiesDownsizes(),
        CreateOrUpdateSubscriptions(),
        UpdatePrices(),
        CompleteOrder(TEMPLATE_NAME_CHANGE),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
