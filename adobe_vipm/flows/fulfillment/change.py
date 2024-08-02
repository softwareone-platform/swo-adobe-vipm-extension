"""
This module contains the logic to implement the change fulfillment flow.
It exposes a single function that is the entrypoint for change order
processing.
"""

import copy
import logging
from collections import Counter

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import (
    TEMPLATE_NAME_CHANGE,
    TEMPLATE_NAME_DELAYED,
)
from adobe_vipm.flows.fulfillment.shared import (
    add_subscription,
    check_adobe_order_fulfilled,
    check_processing_template,
    get_one_time_skus,
    handle_return_orders,
    save_adobe_order_id,
    set_customer_coterm_date_if_null,
    set_subscription_actual_sku,
    switch_order_to_completed,
    switch_order_to_failed,
    update_order_actual_price,
)
from adobe_vipm.flows.sync import sync_agreements_by_agreement_ids
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_adobe_line_item_by_subscription_id,
    get_adobe_order_id,
    get_adobe_subscription_id,
    get_order_line,
    get_partial_sku,
    get_subscription_by_line_and_item_id,
    group_items_by_type,
    is_renewal_window_open,
)

logger = logging.getLogger(__name__)


def _upsize_out_of_win_or_migrated_subscriptions(customer_id, order, lines):
    """
    Manages subscription growth outside of the cancellation period or migrated from Adobe VIP.
    If necessary, adjusts the renewal quantity to match the final quantity of subscriptions
    requested.
    Generates order lines for subscriptions whose final quantity exceeds the current quantity.

    Args:
        customer_id (str): The ID used in Adobe to identify the customer attached
            to this MPT order.
        order (dict): The MPT order from which the Adobe order has been derived.
        lines (list): The MPT order lines that need to be processed.

    Returns:
        list: A list of lines that must be purchased to upsize the subscriptions.
    """
    lines_to_order = []
    adobe_client = get_adobe_client()
    authorization_id = order["authorization"]["id"]
    for line in lines:
        subcription = get_subscription_by_line_and_item_id(
            order["subscriptions"],
            line["item"]["id"],
            line["id"],
        )
        adobe_sub_id = get_adobe_subscription_id(subcription)
        adobe_subscription = adobe_client.get_subscription(
            authorization_id,
            customer_id,
            adobe_sub_id,
        )
        desired_quantity = line["quantity"]
        current_quantity = adobe_subscription["currentQuantity"]
        current_renewal_quantity = adobe_subscription["autoRenewal"]["renewalQuantity"]
        renewal_quantity = desired_quantity
        if desired_quantity > current_quantity:
            # If we have to upsize over the current quantity
            # we have to place an new order for the delta
            # and set the renewal quantity equals to the
            # current quantity (current quantity will be
            # update due to the new order for the delta.
            renewal_quantity = current_quantity
            line_to_order = copy.deepcopy(line)
            line_to_order["oldQuantity"] = current_quantity
            lines_to_order.append(line_to_order)

        if current_renewal_quantity < renewal_quantity:
            adobe_client.update_subscription(
                authorization_id,
                customer_id,
                adobe_sub_id,
                quantity=renewal_quantity,
            )

    return lines_to_order


def _downsize_out_of_win_or_migrated_subscriptions(
    mpt_client, customer_id, order, lines
):
    """
    Reduces the renewal quantity for subscriptions that need to be downsized but were created
    X days before the change order (outside the cancellation window) or migrated from Adobe VIP.

    Args:
        mpt_client: An instance of the MPT client used for communication with the MPT system.
        customer_id (str): The ID used in Adobe to identify the customer attached
            to this MPT order.
        order (dict): The MPT order from which the Adobe order has been derived.
        lines (list): The MPT order lines that need to be processed.

    Returns:
        None
    """
    adobe_client = get_adobe_client()
    authorization_id = order["authorization"]["id"]
    for line in lines:
        subscription = get_subscription_by_line_and_item_id(
            order["subscriptions"],
            line["item"]["id"],
            line["id"],
        )
        adobe_sub_id = get_adobe_subscription_id(subscription)
        adobe_subscription = adobe_client.get_subscription(
            authorization_id,
            customer_id,
            adobe_sub_id,
        )
        if adobe_subscription["autoRenewal"]["renewalQuantity"] != line["quantity"]:
            adobe_client.update_subscription(
                authorization_id,
                customer_id,
                adobe_sub_id,
                quantity=line["quantity"],
            )

    renewal_preview = adobe_client.create_preview_renewal(authorization_id, customer_id)

    mpt_subscription_to_adobe_line_item_map = []
    for line in lines:
        subscription = get_subscription_by_line_and_item_id(
            order["subscriptions"],
            line["item"]["id"],
            line["id"],
        )
        adobe_line_item = get_adobe_line_item_by_subscription_id(
            renewal_preview["lineItems"],
            subscription["externalIds"]["vendor"],
        )
        mpt_subscription_to_adobe_line_item_map.append((subscription, adobe_line_item))

    for subscription, adobe_line_item in mpt_subscription_to_adobe_line_item_map:
        set_subscription_actual_sku(
            mpt_client,
            order,
            subscription,
            adobe_line_item["offerId"],
        )

    adobe_line_items = [
        line_item for _, line_item in mpt_subscription_to_adobe_line_item_map
    ]
    update_order_actual_price(mpt_client, adobe_client, order, lines, adobe_line_items)


def _submit_change_order(mpt_client, customer_id, order):
    adobe_client = get_adobe_client()
    authorization_id = order["authorization"]["id"]
    adobe_order = None
    grouped_items = group_items_by_type(order)
    logger.debug(
        f"item groups: upwin={grouped_items.upsizing_in_win}, "
        f"downin={grouped_items.downsizing_in_win}, "
        f"upout={grouped_items.upsizing_out_win_or_migrated}, ",
        f"downout={grouped_items.downsizing_out_win_or_migrated}",
    )
    try:
        to_add_to_preview = []
        if grouped_items.upsizing_out_win_or_migrated:
            to_add_to_preview = _upsize_out_of_win_or_migrated_subscriptions(
                customer_id,
                order,
                grouped_items.upsizing_out_win_or_migrated,
            )

        if grouped_items.downsizing_out_win_or_migrated:
            _downsize_out_of_win_or_migrated_subscriptions(
                mpt_client,
                customer_id,
                order,
                grouped_items.downsizing_out_win_or_migrated,
            )

        items_to_preview = (
            grouped_items.upsizing_in_win
            + grouped_items.downsizing_in_win
            + to_add_to_preview
        )

        if items_to_preview:
            preview_order = adobe_client.create_preview_order(
                authorization_id,
                customer_id,
                order["id"],
                items_to_preview,
            )

            if grouped_items.downsizing_in_win:
                completed_return_orders, order = handle_return_orders(
                    mpt_client,
                    adobe_client,
                    customer_id,
                    order,
                    grouped_items.downsizing_in_win,
                )

                if not completed_return_orders:
                    return None

            adobe_order = adobe_client.create_new_order(
                authorization_id,
                customer_id,
                preview_order,
            )
            logger.info(
                f'New order created for {order["id"]}: {adobe_order["orderId"]}'
            )
    except AdobeError as e:
        switch_order_to_failed(mpt_client, order, str(e))
        logger.warning(f"Order {order['id']} has been failed: {str(e)}.")
        return None

    if adobe_order:
        order = save_adobe_order_id(mpt_client, order, adobe_order["orderId"])

    return order


def fulfill_change_order(mpt_client, order):
    """
    Fulfills a change order by processing the necessary actions based on the provided parameters.

    Args:
        mpt_client: An instance of the MPT client used for communication with the MPT system.
        order (dict): The MPT order representing the change order to be fulfilled.

    Returns:
        None
    """
    items = [line["item"]["id"] for line in order["lines"]]
    duplicates = [item for item, count in Counter(items).items() if count > 1]
    if duplicates:
        switch_order_to_failed(
            mpt_client,
            order,
            f"The order cannot contain multiple lines for the same item: {','.join(duplicates)}.",
        )
        return

    items = []
    for subscription in order["agreement"]["subscriptions"]:
        for line in subscription["lines"]:
            items.append(line["item"]["id"])

    items.extend(
        [line["item"]["id"] for line in order["lines"] if line["oldQuantity"] == 0]
    )
    duplicates = [item for item, count in Counter(items).items() if count > 1]
    if duplicates:
        switch_order_to_failed(
            mpt_client,
            order,
            f"The order cannot contain new lines for an existing item: {','.join(duplicates)}.",
        )
        return

    adobe_client = get_adobe_client()
    order = set_customer_coterm_date_if_null(mpt_client, adobe_client, order)
    if is_renewal_window_open(order):
        check_processing_template(mpt_client, order, TEMPLATE_NAME_DELAYED)
        return

    check_processing_template(mpt_client, order, TEMPLATE_NAME_CHANGE)

    customer_id = get_adobe_customer_id(order)
    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        order = _submit_change_order(mpt_client, customer_id, order)
        if not order:
            return

    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        switch_order_to_completed(mpt_client, order, TEMPLATE_NAME_CHANGE)
        return
    adobe_order = check_adobe_order_fulfilled(
        mpt_client, adobe_client, order, customer_id, adobe_order_id
    )

    if not adobe_order:
        return

    one_time_skus = get_one_time_skus(mpt_client, order)
    updated_lines = []

    for item in adobe_order["lineItems"]:
        order_line = get_order_line(
            order,
            item["extLineItemNumber"],
        )
        updated_lines.append(order_line)
        if get_partial_sku(item["offerId"]) not in one_time_skus:
            order_subscription = get_subscription_by_line_and_item_id(
                order["subscriptions"],
                order_line["item"]["id"],
                order_line["id"],
            )
            if not order_subscription:
                add_subscription(mpt_client, adobe_client, customer_id, order, item)
            else:
                adobe_sku = item["offerId"]

                set_subscription_actual_sku(
                    mpt_client,
                    order,
                    order_subscription,
                    adobe_sku,
                )

    update_order_actual_price(
        mpt_client, adobe_client, order, updated_lines, adobe_order["lineItems"]
    )
    switch_order_to_completed(mpt_client, order, TEMPLATE_NAME_CHANGE)
    sync_agreements_by_agreement_ids(
        mpt_client, [order["agreement"]["id"]], False, False
    )
