"""
This module contains the logic to implement the termination fulfillment flow.
It exposes a single function that is the entrypoint for termination order
processing.
"""

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.fulfillment.shared import (
    complete_order,
    handle_return_orders,
)
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_adobe_subscription_id,
    get_subscription_by_line_and_item_id,
    group_items_by_type,
)


def _terminate_out_of_win_subscriptions(seller_country, customer_id, order, lines):
    """
    Switch off auto renewal for subscriptions that have to be cancelled but that
    have been more that X days before the termination order (outside cancellation window).

    Args:
        seller_country (str): Country code of the seller attached to this MPT order.
        customer_id (str): The id used in Adobe to identify the customer attached
        to this MPT order.
        order (dct): The MPT order from which the Adobe order has been derived.
        lines (list): The MPT order lines that have to process.
    """
    adobe_client = get_adobe_client()
    for line in lines:
        subcription = get_subscription_by_line_and_item_id(
            order["subscriptions"],
            line["item"]["id"],
            line["id"],
        )
        adobe_sub_id = get_adobe_subscription_id(subcription)
        adobe_subscription = adobe_client.get_subscription(
            seller_country,
            customer_id,
            adobe_sub_id,
        )
        if adobe_subscription["autoRenewal"]["enabled"]:
            adobe_client.update_subscription(
                seller_country,
                customer_id,
                adobe_sub_id,
                auto_renewal=False,
            )


def fulfill_termination_order(mpt_client, seller_country, order):
    """
    Fulfills a termination order with Adobe.
    Adobe allow to terminate a subscription with a cancellation window
    (X days from the first order).
    For subscriptions that are outside such window the auto renewal
    will be switched off.

    Args:
        mpt_client (MPTClient):  an instance of the Marketplace platform client.
        seller_country (str): Country code of the seller attached to this MPT order.
        order (dct): The MPT termination order.
    """
    adobe_client = get_adobe_client()
    customer_id = get_adobe_customer_id(order)

    grouped_items = group_items_by_type(order)
    if grouped_items.downsizing_out_win:
        _terminate_out_of_win_subscriptions(
            seller_country, customer_id, order, grouped_items.downsizing_out_win
        )

    has_orders_to_return = bool(
        grouped_items.upsizing_in_win + grouped_items.downsizing_in_win
    )
    if not has_orders_to_return:
        complete_order(mpt_client, order)
        return

    completed_return_orders, order = handle_return_orders(
        mpt_client,
        adobe_client,
        seller_country,
        customer_id,
        order,
        grouped_items.upsizing_in_win + grouped_items.downsizing_in_win,
    )

    if completed_return_orders:
        complete_order(mpt_client, order)
