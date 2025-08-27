"""
This module contains the logic to implement the change fulfillment flow.

It exposes a single function that is the entrypoint for change order
processing.
"""

import itertools
import logging
from functools import partial

from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import (
    ERR_INVALID_RENEWAL_STATE,
    ERR_NO_RETURABLE_ERRORS_FOUND,
    TEMPLATE_NAME_CHANGE,
    Param,
)
from adobe_vipm.flows.context import Context
from adobe_vipm.flows.fulfillment.shared import (
    CompleteOrder,
    CreateOrUpdateAssets,
    CreateOrUpdateSubscriptions,
    GetPreviewOrder,
    GetReturnOrders,
    NullifyFlexDiscountParam,
    SetOrUpdateCotermDate,
    SetSubscriptionTemplate,
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
    ValidateSkuAvailability,
)
from adobe_vipm.flows.pipeline import Pipeline, Step
from adobe_vipm.flows.utils import (
    get_adobe_subscription_id,
    get_subscription_by_line_and_item_id,
    notify_not_updated_subscriptions,
)
from adobe_vipm.flows.utils.customer import is_within_coterm_window
from adobe_vipm.flows.utils.subscription import get_subscription_by_line_subs_id
from adobe_vipm.utils import get_partial_sku

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

    def __call__(self, client, context, next_step):  # noqa: C901
        """Compute a map of returnable orders."""
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
            subscription_id = get_subscription_by_line_subs_id(
                context.order["agreement"]["subscriptions"],
                line
            )
            returnable_orders = adobe_client.get_returnable_orders_by_subscription_id(
                context.authorization_id,
                context.adobe_customer_id,
                subscription_id,
                context.adobe_customer["cotermDate"],
                return_orders=context.adobe_return_orders.get(sku)
            )
            if not returnable_orders:
                logger.info("%s: no returnable orders found for sku %s", context, sku)
                continue
            returnable_orders_count += len(returnable_orders)
            returnable_by_quantity = {}
            for r in range(len(returnable_orders), 0, -1):
                for sub in itertools.combinations(returnable_orders, r):
                    returnable_by_quantity[sum(line_item.quantity for line_item in sub)] = sub

            delta = line["oldQuantity"] - line["quantity"]
            if delta not in returnable_by_quantity:
                context.adobe_returnable_orders[sku] = None
                continue

            context.adobe_returnable_orders[sku] = returnable_by_quantity[delta]
        logger.info("%s: found %s returnable orders.", context, returnable_orders_count)
        next_step(client, context)


class ValidateReturnableOrders(Step):
    """
    Validates that all the lines that should be downsized can be processed.

    The sum of the quantity of one or more orders that can be returned
    matched the downsize quantity.
    If there are SKUs that cannot be downsized and no return order
    has been placed previously, the order will be failed.
    This can happen if the draft validation have been skipped or the order
    has been switched to `Processing` if a day or more have passed after
    the draft validation.
    """

    def __call__(self, client, context, next_step):
        """Validates that all the lines that should be downsized can be processed."""
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
            logger.info("%s: failed due to %s", context, error["message"])
            return

        next_step(client, context)


def _check_item_in_order(line, order_item):
    return get_partial_sku(order_item["offerId"]) == line["item"]["externalIds"]["vendor"]


def _is_invalid_renewal_state_ok(context, line):
    invalid_renewal_state_allowed = True
    check_item_in_order = partial(_check_item_in_order, line)
    if context.adobe_new_order and find_first(
        check_item_in_order, context.adobe_new_order["lineItems"]
    ):
        invalid_renewal_state_allowed = (
            context.adobe_new_order["status"] == AdobeStatus.PROCESSED.value
        )
        if invalid_renewal_state_allowed:
            logger.info("> Vendor order with the item has status PROCESSED")

    return invalid_renewal_state_allowed


class UpdateRenewalQuantities(Step):
    """
    Updates the Adobe subscriptions renewal quantity if it doesn't match the agreement quantity.

    If process_downsize_lines is False, the downsize lines will not be processed.
    If process_upsize_lines is False, the upsize and new lines will not be processed.
    The upsizes and new lines are processed first, to process correctly the 3yc
    to maintain the compliant with the 3yc minimum quantities.
    """

    def __init__(self):
        self.error = None

    def __call__(self, client, context, next_step):
        """Updates the Adobe subscriptions renewal quantity if it doesn't match."""
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
        old_qty = adobe_subscription["autoRenewal"][Param.RENEWAL_QUANTITY.value]

        if old_qty != qty:
            try:
                adobe_client.update_subscription(
                    context.authorization_id,
                    context.adobe_customer_id,
                    adobe_sub_id,
                    quantity=qty,
                )
            except AdobeAPIError as error:
                invalid_renewal_state_allowed = False
                if error.code == AdobeStatus.INVALID_RENEWAL_STATE and old_qty < qty:
                    logger.info(
                        "Got invalid renewal state error for subscription %s while updating"
                        " quantity %s -> %s",
                        subscription["id"],
                        old_qty,
                        qty,
                    )
                    invalid_renewal_state_allowed = _is_invalid_renewal_state_ok(context, line)
                if not (
                    invalid_renewal_state_allowed
                    or (
                        error.code == AdobeStatus.LINE_ITEM_OFFER_ID_EXPIRED
                        and context.adobe_new_order
                    )
                ):
                    logger.exception(
                        "%s: failed to update renewal quantity for %s (%s)",
                        context,
                        subscription["id"],
                        adobe_sub_id,
                    )
                    notify_not_updated_subscriptions(
                        context.order["id"],
                        f"Error updating subscription {subscription['id']}, {error}",
                        [],
                        context.product_id,
                    )
                    self.error = error
                    return

            logger.info(
                "%s: update renewal quantity for sub %s (%s) %s -> %s",
                context,
                subscription["id"],
                adobe_sub_id,
                old_qty,
                qty,
            )
            context.updated.append({
                "subscription_vendor_id": adobe_sub_id,
                "old_quantity": old_qty,
                "new_quantity": qty,
            })

    def _handle_subscription_update_error(self, adobe_client, client, context, e):
        self._rollback_updated_subscriptions(adobe_client, context)
        if e.code in {
            AdobeStatus.INVALID_RENEWAL_STATE,
            AdobeStatus.SUBSCRIPTION_INACTIVE,
        }:
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
            logger.exception("Error rolling back updated subscriptions")


class UpdateRenewalQuantitiesDownsizes(UpdateRenewalQuantities):
    """Updates the Adobe subscriptions renewal quantity for downsized items."""

    def _get_lines(self, context):
        return context.downsize_lines


def fulfill_change_order(client, order):
    """
    Fulfills a change order by processing the necessary actions based on the provided parameters.

    Args:
        client (MPTClient): An instance of the MPT client used for communication
        with the MPT system.
        order (dict): The MPT order representing the change order to be fulfilled.

    Returns:
        None
    """
    pipeline = Pipeline(
        SetupContext(),
        StartOrderProcessing(TEMPLATE_NAME_CHANGE),
        SetupDueDate(),
        ValidateDuplicateLines(),
        SetOrUpdateCotermDate(),
        ValidateRenewalWindow(),
        ValidateSkuAvailability(is_validation=False),
        GetReturnOrders(),
        GetReturnableOrders(),
        ValidateReturnableOrders(),
        Validate3YCCommitment(),
        GetPreviewOrder(),
        UpdatePrices(),
        SubmitNewOrder(),
        UpdateRenewalQuantities(),
        SubmitReturnOrders(),
        UpdateRenewalQuantitiesDownsizes(),
        CreateOrUpdateAssets(),
        CreateOrUpdateSubscriptions(),
        CompleteOrder(TEMPLATE_NAME_CHANGE),
        SetSubscriptionTemplate(),
        NullifyFlexDiscountParam(),
        SyncAgreement(),
    )
    context = Context(order=order)
    pipeline.run(client, context)
