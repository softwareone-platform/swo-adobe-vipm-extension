"""
This module contains the logic to implement the transfer fulfillment flow.
It exposes a single function that is the entrypoint for transfer order
processing.
A transfer order is a purchase order for an agreement that will be migrated
from the old Adobe VIP partner program to the new Adobe VIP Marketplace partner
program.
"""

import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    STATUS_PENDING,
    STATUS_PROCESSED,
    STATUS_TRANSFER_INVALID_MEMBERSHIP,
    STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
)
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import ERR_ADOBE_MEMBERSHIP_ID, PARAM_MEMBERSHIP_ID
from adobe_vipm.flows.fulfillment.shared import (
    add_subscription,
    complete_order,
    handle_retries,
    save_adobe_customer_id,
    save_adobe_order_id,
    switch_order_to_failed,
    switch_order_to_query,
)
from adobe_vipm.flows.utils import (
    get_adobe_membership_id,
    get_adobe_order_id,
    get_ordering_parameter,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


def _handle_transfer_preview_error(client, order, error):
    if error.code in (
        STATUS_TRANSFER_INVALID_MEMBERSHIP,
        STATUS_TRANSFER_INVALID_MEMBERSHIP_OR_TRANSFER_IDS,
    ):
        param = get_ordering_parameter(order, PARAM_MEMBERSHIP_ID)
        order = set_ordering_parameter_error(
            order,
            PARAM_MEMBERSHIP_ID,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=str(error)),
        )
        switch_order_to_query(client, order)
        return

    switch_order_to_failed(client, order, str(error))


def _check_transfer(mpt_client, seller_country, order, membership_id):
    """
    Checks the validity of a transfer order based on the provided parameters.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        seller_country (str): Country code of the seller attached to this MPT order.
        order (dict): The MPT order being processed.
        membership_id (str): The Adobe membership ID associated with the transfer.

    Returns:
        bool: True if the transfer is valid, False otherwise.
    """

    adobe_client = get_adobe_client()
    transfer_preview = None
    try:
        transfer_preview = adobe_client.preview_transfer(seller_country, membership_id)
    except AdobeError as e:
        _handle_transfer_preview_error(mpt_client, order, e)
        logger.warning(f"Transfer order {order['id']} has been failed: {str(e)}.")
        return False

    adobe_lines = sorted(
        [
            (item["offerId"][:10], item["quantity"])
            for item in transfer_preview["items"]
        ],
        key=lambda i: i[0],
    )

    order_lines = sorted(
        [
            (line["item"]["externalIds"]["vendor"], line["quantity"])
            for line in order["lines"]
        ],
        key=lambda i: i[0],
    )
    if adobe_lines != order_lines:
        reason = (
            "The items owned by the given membership don't "
            f"match the order (sku or quantity): {','.join([line[0] for line in adobe_lines])}."
        )
        switch_order_to_failed(mpt_client, order, reason)
        logger.warning(f"Transfer 0rder {order['id']} has been failed: {reason}.")
        return False
    return True


def _submit_transfer_order(mpt_client, seller_country, order, membership_id):
    """
    Submits a transfer order to the Adobe API based on the provided parameters.
    In case the Adobe API returns errors, the order will be switched to failed.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        seller_country (str): Country code of the seller attached to this MPT order.
        order (dict): The MPT order to be submitted.
        membership_id (str): The Adobe membership ID associated with the transfer.

    Returns:
        dict or None: The Adobe transfer order if successful, None otherwise.
    """
    adobe_client = get_adobe_client()
    adobe_transfer_order = None
    try:
        adobe_transfer_order = adobe_client.create_transfer(
            seller_country, order["id"], membership_id
        )
    except AdobeError as e:
        switch_order_to_failed(mpt_client, order, str(e))
        logger.warning(f"Transfer order {order['id']} has been failed: {str(e)}.")
        return None

    adobe_transfer_order_id = adobe_transfer_order["transferId"]
    return save_adobe_order_id(mpt_client, order, adobe_transfer_order_id)


def _check_adobe_transfer_order_fulfilled(
    mpt_client, seller_country, order, membership_id, adobe_transfer_id
):
    """
    Checks the fulfillment status of an Adobe transfer order.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        seller_country (str): Country code of the seller attached to this MPT order.
        order (dict): The MPT order being processed.
        membership_id (str): The Adobe membership ID associated with the transfer.
        adobe_transfer_id (str): The Adobe transfer order ID.

    Returns:
        dict or None: The Adobe transfer order if fulfilled, None otherwise.
    """
    adobe_client = get_adobe_client()
    adobe_order = adobe_client.get_transfer(
        seller_country,
        membership_id,
        adobe_transfer_id,
    )
    if adobe_order["status"] == STATUS_PENDING:
        handle_retries(mpt_client, order, adobe_transfer_id)
        return
    elif adobe_order["status"] != STATUS_PROCESSED:
        reason = f"Unexpected status ({adobe_order['status']}) received from Adobe."
        switch_order_to_failed(mpt_client, order, reason)
        logger.warning(f"Transfer {order['id']} has been failed: {reason}.")
        return
    return adobe_order


def fulfill_transfer_order(mpt_client, seller_country, order):
    """
    Fulfills a transfer order by processing the necessary actions based on the provided parameters.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        seller_country (str): Country code of the seller attached to this MPT order.
        order (dict): The MPT transfer order to be fulfilled.

    Returns:
        None
    """
    adobe_client = get_adobe_client()
    membership_id = get_adobe_membership_id(order)
    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        if not _check_transfer(mpt_client, seller_country, order, membership_id):
            return

        order = _submit_transfer_order(mpt_client, seller_country, order, membership_id)
        if not order:
            return

        adobe_order_id = order["externalIds"]["vendor"]

    adobe_transfer_order = _check_adobe_transfer_order_fulfilled(
        mpt_client, seller_country, order, membership_id, adobe_order_id
    )
    if not adobe_transfer_order:
        return

    customer_id = adobe_transfer_order["customerId"]
    order = save_adobe_customer_id(mpt_client, order, customer_id)
    for item in adobe_transfer_order["lineItems"]:
        add_subscription(
            mpt_client, adobe_client, seller_country, customer_id, order, item
        )
    complete_order(mpt_client, order)
