"""
This module contains the logic to implement the purchase fulfillment flow.
It exposes a single function that is the entrypoint for purchase order
processing.
"""

import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import STATUS_INVALID_ADDRESS, STATUS_INVALID_FIELDS
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_ADDRESS,
    ERR_ADOBE_COMPANY_NAME,
    ERR_ADOBE_CONTACT,
    ERR_ADOBE_PREFERRED_LANGUAGE,
    ITEM_TYPE_ORDER_LINE,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_PREFERRED_LANGUAGE,
)
from adobe_vipm.flows.fulfillment.shared import (
    add_subscription,
    check_adobe_order_fulfilled,
    save_adobe_customer_id,
    save_adobe_order_id,
    switch_order_to_completed,
    switch_order_to_failed,
    switch_order_to_query,
    update_order_actual_price,
)
from adobe_vipm.flows.helpers import prepare_customer_data
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_adobe_order_id,
    get_ordering_parameter,
    set_ordering_parameter_error,
)

logger = logging.getLogger(__name__)


def _handle_customer_error(client, order, error):
    """
    Processes the error received from the Adobe API during customer creation.
    If the error is related to a customer parameter, the parameter error attribute
    is set, and the MPT order is switched to the 'query' status.
    Other errors will result in the MPT order being marked as failed.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The MPT order that is being processed.
        error (AdobeAPIError): The error received from the Adobe API.

    Returns:
        None
    """
    if error.code not in (STATUS_INVALID_ADDRESS, STATUS_INVALID_FIELDS):
        switch_order_to_failed(client, order, str(error))
        return
    if error.code == STATUS_INVALID_ADDRESS:
        param = get_ordering_parameter(order, PARAM_ADDRESS)
        order = set_ordering_parameter_error(
            order,
            PARAM_ADDRESS,
            ERR_ADOBE_ADDRESS.to_dict(title=param["name"], details=str(error)),
        )
    else:
        if "companyProfile.companyName" in error.details:
            param = get_ordering_parameter(order, PARAM_COMPANY_NAME)
            order = set_ordering_parameter_error(
                order,
                PARAM_COMPANY_NAME,
                ERR_ADOBE_COMPANY_NAME.to_dict(title=param["name"], details=str(error)),
            )
        if "companyProfile.preferredLanguage" in error.details:
            param = get_ordering_parameter(order, PARAM_PREFERRED_LANGUAGE)
            order = set_ordering_parameter_error(
                order,
                PARAM_PREFERRED_LANGUAGE,
                ERR_ADOBE_PREFERRED_LANGUAGE.to_dict(
                    title=param["name"], details=str(error)
                ),
            )
        if len(
            list(
                filter(
                    lambda x: x.startswith("companyProfile.contacts[0]"), error.details
                )
            )
        ):
            param = get_ordering_parameter(order, PARAM_CONTACT)
            order = set_ordering_parameter_error(
                order,
                PARAM_CONTACT,
                ERR_ADOBE_CONTACT.to_dict(title=param["name"], details=str(error)),
            )

    switch_order_to_query(client, order)


def create_customer_account(client, order):
    """
    Creates a customer account in Adobe for the new agreement that belongs to the order
    currently being processed.

    Args:
        client (MPTClient): An instance of the Marketplace platform client.
        order (dict): The order that is being processed.

    Returns:
        dict: The order updated with the customer ID set on the corresponding
        fulfillment parameter.
    """
    adobe_client = get_adobe_client()
    try:
        order, customer_data = prepare_customer_data(client, order)
        external_id = order["agreement"]["id"]
        seller_id = order["agreement"]["seller"]["id"]
        authorization_id = order["authorization"]["id"]
        customer_id = adobe_client.create_customer_account(
            authorization_id, seller_id, external_id, customer_data
        )
        return save_adobe_customer_id(client, order, customer_id)
    except AdobeError as e:
        logger.error(repr(e))
        _handle_customer_error(client, order, e)


def _submit_new_order(mpt_client, customer_id, order):
    adobe_client = get_adobe_client()
    adobe_order = None
    try:
        authorization_id = order["authorization"]["id"]
        preview_order = adobe_client.create_preview_order(
            authorization_id, customer_id, order["id"], order["lines"]
        )
        adobe_order = adobe_client.create_new_order(
            authorization_id,
            customer_id,
            preview_order,
        )
        logger.info(f'New order created for {order["id"]}: {adobe_order["orderId"]}')
    except AdobeError as e:
        switch_order_to_failed(mpt_client, order, str(e))
        logger.warning(f"Order {order['id']} has been failed: {str(e)}.")
        return None

    return save_adobe_order_id(mpt_client, order, adobe_order["orderId"])


def fulfill_purchase_order(mpt_client, order):
    """
    Fulfills a purchase order by processing the necessary actions based on the provided parameters.

    Args:
        mpt_client: An instance of the MPT client used for communication with the MPT system.
        order (dict): The MPT order representing the purchase order to be fulfilled.

    Returns:
        None
    """
    adobe_client = get_adobe_client()
    customer_id = get_adobe_customer_id(order)
    if not customer_id:
        order = create_customer_account(mpt_client, order)
        if not order:
            return

    customer_id = get_adobe_customer_id(order)
    adobe_order_id = get_adobe_order_id(order)
    if not adobe_order_id:
        order = _submit_new_order(mpt_client, customer_id, order)
        if not order:
            return
    adobe_order_id = order["externalIds"]["vendor"]
    adobe_order = check_adobe_order_fulfilled(
        mpt_client, adobe_client, order, customer_id, adobe_order_id
    )
    if not adobe_order:
        return

    for item in adobe_order["lineItems"]:
        add_subscription(
            mpt_client, adobe_client, customer_id, order, ITEM_TYPE_ORDER_LINE, item
        )
    update_order_actual_price(
        mpt_client, order, order["lines"], adobe_order["lineItems"]
    )

    switch_order_to_completed(mpt_client, order)
