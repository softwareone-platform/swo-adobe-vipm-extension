"""
This module contains the logic to implement the purchase fulfillment flow.
It exposes a single function that is the entrypoint for purchase order
processing.
"""

import logging
from collections import Counter

from django.conf import settings
from swo.mpt.extensions.runtime.djapp.conf import get_for_product

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    STATUS_INVALID_ADDRESS,
    STATUS_INVALID_FIELDS,
    STATUS_INVALID_MINIMUM_QUANTITY,
)
from adobe_vipm.adobe.errors import AdobeError
from adobe_vipm.adobe.utils import get_3yc_commitment_request
from adobe_vipm.flows.constants import (
    ERR_3YC_NO_MINIMUMS,
    ERR_3YC_QUANTITY_CONSUMABLES,
    ERR_3YC_QUANTITY_LICENSES,
    ERR_ADOBE_ADDRESS,
    ERR_ADOBE_COMPANY_NAME,
    ERR_ADOBE_CONTACT,
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_LICENSES,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    TEMPLATE_NAME_PURCHASE,
)
from adobe_vipm.flows.fulfillment.shared import (
    add_subscription,
    check_adobe_order_fulfilled,
    check_processing_template,
    get_one_time_skus,
    save_adobe_customer_data,
    save_adobe_order_id,
    save_next_sync_date,
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
    get_partial_sku,
    set_order_error,
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
    if error.code not in (
        STATUS_INVALID_ADDRESS,
        STATUS_INVALID_FIELDS,
        STATUS_INVALID_MINIMUM_QUANTITY,
    ):
        switch_order_to_failed(client, order, str(error))
        return
    if error.code == STATUS_INVALID_ADDRESS:
        param = get_ordering_parameter(order, PARAM_ADDRESS)
        order = set_ordering_parameter_error(
            order,
            PARAM_ADDRESS,
            ERR_ADOBE_ADDRESS.to_dict(title=param["name"], details=str(error)),
        )
    elif error.code == STATUS_INVALID_MINIMUM_QUANTITY:
        if "LICENSE" in str(error):
            param = get_ordering_parameter(order, PARAM_3YC_LICENSES)
            order = set_ordering_parameter_error(
                order,
                PARAM_3YC_LICENSES,
                ERR_3YC_QUANTITY_LICENSES.to_dict(title=param["name"]),
                required=False,
            )
        if "CONSUMABLES" in str(error):
            param = get_ordering_parameter(order, PARAM_3YC_CONSUMABLES)
            order = set_ordering_parameter_error(
                order,
                PARAM_3YC_CONSUMABLES,
                ERR_3YC_QUANTITY_CONSUMABLES.to_dict(title=param["name"]),
                required=False,
            )
        if not error.details:
            param_licenses = get_ordering_parameter(order, PARAM_3YC_LICENSES)
            param_consumables = get_ordering_parameter(order, PARAM_3YC_CONSUMABLES)
            order = set_order_error(
                order,
                ERR_3YC_NO_MINIMUMS.to_dict(
                    title_min_licenses=param_licenses["name"],
                    title_min_consumables=param_consumables["name"],
                ),
            )
    else:
        if "companyProfile.companyName" in error.details:
            param = get_ordering_parameter(order, PARAM_COMPANY_NAME)
            order = set_ordering_parameter_error(
                order,
                PARAM_COMPANY_NAME,
                ERR_ADOBE_COMPANY_NAME.to_dict(title=param["name"], details=str(error)),
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
        if not customer_data.get("contact"):
            param = get_ordering_parameter(order, PARAM_CONTACT)
            order = set_ordering_parameter_error(
                order,
                PARAM_CONTACT,
                ERR_ADOBE_CONTACT.to_dict(
                    title=param["name"], details="it is mandatory."
                ),
            )

            switch_order_to_query(client, order)
            return

        external_id = order["agreement"]["id"]
        product_id = order["agreement"]["product"]["id"]
        seller_id = order["agreement"]["seller"]["id"]
        authorization_id = order["authorization"]["id"]
        market_segment = get_for_product(settings, "PRODUCT_SEGMENT", product_id)
        customer = adobe_client.create_customer_account(
            authorization_id, seller_id, external_id, market_segment, customer_data
        )
        customer_id = customer["customerId"]

        return save_adobe_customer_data(
            client,
            order,
            customer_id,
            request_3yc_status=get_3yc_commitment_request(customer).get("status"),
        )
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

    items = [line["item"]["id"] for line in order["lines"]]
    duplicates = [item for item, count in Counter(items).items() if count > 1]
    if duplicates:
        switch_order_to_failed(
            mpt_client,
            order,
            f"The order cannot contain multiple lines for the same item: {','.join(duplicates)}.",
        )
        return

    check_processing_template(mpt_client, order, TEMPLATE_NAME_PURCHASE)

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
    one_time_skus = get_one_time_skus(mpt_client, order)
    commitment_date = None
    for item in adobe_order["lineItems"]:
        if get_partial_sku(item["offerId"]) in one_time_skus:
            continue

        subscription = add_subscription(
            mpt_client, adobe_client, customer_id, order, item
        )
        if subscription and not commitment_date:  # pragma: no branch
            # subscription are cotermed so it's ok to take the last created
            commitment_date = subscription["commitmentDate"]

    if commitment_date:  # pragma: no branch
        order = save_next_sync_date(mpt_client, order, commitment_date)

    update_order_actual_price(
        mpt_client, order, order["lines"], adobe_order["lineItems"]
    )

    switch_order_to_completed(mpt_client, order, TEMPLATE_NAME_PURCHASE)
