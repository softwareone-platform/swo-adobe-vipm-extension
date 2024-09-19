"""
This module contains orders helper functions.
"""

import logging

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows.constants import (
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
    get_retry_count,
    reset_order_error,
    reset_ordering_parameters_error,
    set_customer_data,
    split_downsizes_and_upsizes,
)

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


class PrepareCustomerData(Step):
    def __call__(self, client, context, next_step):
        licensee = context.order["agreement"]["licensee"]
        address = licensee["address"]
        contact = licensee.get("contact")

        customer_data_updated = False

        if not context.customer_data.get(PARAM_COMPANY_NAME):
            context.customer_data[PARAM_COMPANY_NAME] = licensee["name"]
            customer_data_updated = True

        if not context.customer_data.get(PARAM_ADDRESS):
            context.customer_data[PARAM_ADDRESS] = {
                "country": address["country"],
                "state": address["state"],
                "city": address["city"],
                "addressLine1": address["addressLine1"],
                "addressLine2": address.get("addressLine2"),
                "postCode": address["postCode"],
            }
            customer_data_updated = True

        if not context.customer_data.get(PARAM_CONTACT) and contact:
            context.customer_data[PARAM_CONTACT] = {
                "firstName": contact["firstName"],
                "lastName": contact["lastName"],
                "email": contact["email"],
                "phone": contact.get("phone"),
            }
            customer_data_updated = True

        if customer_data_updated:
            context.order = set_customer_data(context.order, context.customer_data)
            update_order(
                client,
                context.order_id,
                parameters=context.order["parameters"],
            )

        next_step(client, context)


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
        context.seller_id = context.order["agreement"]["seller"]["id"]
        context.currency = context.order["agreement"]["listing"]["priceList"]["currency"]
        context.customer_data = get_customer_data(context.order)
        context.market_segment = get_market_segment(context.product_id)
        context.adobe_customer_id = get_adobe_customer_id(context.order)
        if context.adobe_customer_id:
            context.adobe_customer = adobe_client.get_customer(
                context.authorization_id,
                context.adobe_customer_id,
            )
        context.adobe_new_order_id = get_adobe_order_id(context.order)
        logger.info(f"{context}: initialization completed.")
        next_step(client, context)
