"""
This module contains orders helper functions.
"""

import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.airtable import get_prices_for_skus
from adobe_vipm.flows.constants import (
    FAKE_CUSTOMERS_IDS,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
)
from adobe_vipm.flows.mpt import (
    get_agreement,
    get_licensee,
    update_order,
)
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_adobe_order_id,
    get_customer_data,
    get_market_segment,
    get_order_line_by_sku,
    get_retry_count,
    reset_order_error,
    reset_ordering_parameters_error,
    set_customer_data,
    split_downsizes_and_upsizes,
)
from adobe_vipm.utils import get_partial_sku

logger = logging.getLogger(__name__)


def populate_order_info(client, order):
    """
    Enrich the order with the full representation of the
    agreement object.

    Args:
        client (MPTClient): an instance of the Marketplace platform client.
        order (dict): the order that is being processed.

    Returns:
        dict: The enriched order.
    """
    order["agreement"] = get_agreement(client, order["agreement"]["id"])
    order["agreement"]["licensee"] = get_licensee(
        client, order["agreement"]["licensee"]["id"]
    )

    return order


def prepare_customer_data(client, order):
    """
    Try to get customer data from ordering parameters. If they are empty,
    they will be filled with data from the buyer object related to the
    current order that will than be updated.

    Args:
        client (MPTClient): an instance of the Marketplace platform client.
        order (dict): the order that is being processed.

    Returns:
        tuple: a tuple which first item is the updated order and the second
        a dictionary with the data of the customer that must be created in Adobe.
    """
    licensee = order["agreement"]["licensee"]
    address = licensee["address"]
    contact = licensee.get("contact")

    customer_data = get_customer_data(order)

    if not customer_data.get(PARAM_COMPANY_NAME):
        customer_data[PARAM_COMPANY_NAME] = licensee["name"]

    if not customer_data.get(PARAM_ADDRESS):
        customer_data[PARAM_ADDRESS] = {
            "country": address["country"],
            "state": address["state"],
            "city": address["city"],
            "addressLine1": address["addressLine1"],
            "addressLine2": address.get("addressLine2"),
            "postCode": address["postCode"],
        }

    if not customer_data.get(PARAM_CONTACT) and contact:
        customer_data[PARAM_CONTACT] = {
            "firstName": contact["firstName"],
            "lastName": contact["lastName"],
            "email": contact["email"],
            "phone": contact.get("phone"),
        }

    order = set_customer_data(order, customer_data)

    update_order(
        client,
        order["id"],
        parameters=order["parameters"],
    )

    return order, get_customer_data(order)

def _update_purchase_prices(order, line_items):
    adobe_skus = [item["offerId"] for item in line_items]
    currency = order["agreement"]["listing"]["priceList"]["currency"]
    product_id = order["agreement"]["product"]["id"]
    prices = get_prices_for_skus(product_id, currency, adobe_skus)

    updated_lines = []
    for preview_item in line_items:
        order_line = get_order_line_by_sku(
            order, get_partial_sku(preview_item["offerId"])
        )
        order_line.setdefault("price", {})
        order_line["price"]["unitPP"] = prices[preview_item["offerId"]]
        updated_lines.append(order_line)
    order["lines"] = updated_lines

    return order


def update_purchase_prices(adobe_client, order):
    """
    Creates a preview order in adobe to get the full SKU list to update items prices
    during draft validation.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        adobe_client (AdobeClient): An instance of the Adobe client for communication with the
            Adobe API.
        order (dict): The MPT order to which the subscription will be added.

    Returns:
        dict: The updated order
    """
    product_segment = get_market_segment(order["agreement"]["product"]["id"])
    customer_id = get_adobe_customer_id(order) or FAKE_CUSTOMERS_IDS[product_segment]
    authorization_id = order["authorization"]["id"]
    preview_order = adobe_client.create_preview_order(
        authorization_id, customer_id, order["id"], order["lines"]
    )
    return _update_purchase_prices(
        order,
        preview_order["lineItems"],
    )


class SetupContext(Step):
    """
    Initialize the processing context.
    Enrich the order with the full representations of the agreement and the licensee
    retrieving them.
    If the Adobe customerId fulfillment parameter is set, then retrieve the customer
    object from adobe and set it.
    """
    def __call__(self, client, context, next_step):
        adobe_client = get_adobe_client()
        context.order = reset_order_error(context.order)
        context.order = reset_ordering_parameters_error(context.order)
        context.order["agreement"] = get_agreement(client, context.order["agreement"]["id"])
        context.order["agreement"]["licensee"] = get_licensee(
            client, context.order["agreement"]["licensee"]["id"]
        )
        context.downsize_lines, context.upsize_lines = split_downsizes_and_upsizes(context.order)
        context.current_attempt = get_retry_count(context.order)
        context.order_id = context.order["id"]
        context.type = context.order["type"]
        context.agreement_id = context.order["agreement"]["id"]
        context.authorization_id = context.order["authorization"]["id"]
        context.product_id = context.order["agreement"]["product"]["id"]
        context.currency = context.order["agreement"]["listing"]["priceList"]["currency"]
        context.adobe_customer_id = get_adobe_customer_id(context.order)
        if context.adobe_customer_id:
            context.adobe_customer = adobe_client.get_customer(
                context.authorization_id,
                context.adobe_customer_id,
            )
        context.adobe_new_order_id = get_adobe_order_id(context.order)
        logger.info(f"{context}: initialization completed.")
        next_step(client, context)
