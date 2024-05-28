"""
This module contains the logic to implement the termination fulfillment flow.
It exposes a single function that is the entrypoint for termination order
processing.
"""

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.constants import TEMPLATE_NAME_TERMINATION
from adobe_vipm.flows.fulfillment.shared import (
    check_processing_template,
    handle_return_orders,
    switch_order_to_completed,
)
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_adobe_subscription_id,
    get_subscription_by_line_and_item_id,
    group_items_by_type,
)


def _terminate_out_of_win_or_migrated_subscriptions(customer_id, order, lines):
    """
    Switch off auto renewal for subscriptions that have to be cancelled but that
    have been more that X days before the termination order (outside cancellation window).

    Args:
        customer_id (str): The id used in Adobe to identify the customer attached
        to this MPT order.
        order (dct): The MPT order from which the Adobe order has been derived.
        lines (list): The MPT order lines that have to process.
    """
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
        if adobe_subscription["autoRenewal"]["enabled"]:
            adobe_client.update_subscription(
                authorization_id,
                customer_id,
                adobe_sub_id,
                auto_renewal=False,
            )


def fulfill_termination_order(mpt_client, order):
    """
    Fulfills a termination order with Adobe.
    Adobe allow to terminate a subscription with a cancellation window
    (X days from the first order).
    For subscriptions that are outside such window the auto renewal
    will be switched off.

    Args:
        mpt_client (MPTClient):  an instance of the Marketplace platform client.
        order (dct): The MPT termination order.
    """
    check_processing_template(mpt_client, order, TEMPLATE_NAME_TERMINATION)
    adobe_client = get_adobe_client()
    customer_id = get_adobe_customer_id(order)

    grouped_items = group_items_by_type(order)
    if grouped_items.downsizing_out_win_or_migrated:
        _terminate_out_of_win_or_migrated_subscriptions(
            customer_id, order, grouped_items.downsizing_out_win_or_migrated
        )

    has_orders_to_return = bool(
        grouped_items.upsizing_in_win + grouped_items.downsizing_in_win
    )
    if not has_orders_to_return:
        switch_order_to_completed(mpt_client, order, TEMPLATE_NAME_TERMINATION)
        return

    completed_return_orders, order = handle_return_orders(
        mpt_client,
        adobe_client,
        customer_id,
        order,
        grouped_items.upsizing_in_win + grouped_items.downsizing_in_win,
    )

    if completed_return_orders:
        switch_order_to_completed(mpt_client, order, TEMPLATE_NAME_TERMINATION)
