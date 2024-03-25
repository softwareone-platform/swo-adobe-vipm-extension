"""
This module contains orders helper functions.
"""
import logging

from adobe_vipm.flows.constants import (
    FAKE_CUSTOMER_ID,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_PREFERRED_LANGUAGE,
)
from adobe_vipm.flows.mpt import (
    get_agreement,
    get_pricelist_items_by_product_items,
    get_product_items_by_skus,
    update_order,
)
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_customer_data,
    get_order_line_by_sku,
    set_customer_data,
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

    return order


def prepare_customer_data(client, order, buyer):
    """
    Try to get customer data from ordering parameters. If they are empty,
    they will be filled with data from the buyer object related to the
    current order that will than be updated.

    Args:
        client (MPTClient): an instance of the Marketplace platform client.
        order (dict): the order that is being processed.
        buyer (dict): the buyer that can be used to take the customer data
        from.

    Returns:
        tuple: a tuple which first item is the updated order and the second
        a dictionary with the data of the customer that must be created in Adobe.
    """
    customer_data = get_customer_data(order)
    if not all(customer_data.values()):
        order = set_customer_data(
            order,
            {
                PARAM_COMPANY_NAME: buyer["name"],
                PARAM_PREFERRED_LANGUAGE: "en-US",
                PARAM_ADDRESS: {
                    "country": buyer["address"]["country"],
                    "state": buyer["address"]["state"],
                    "city": buyer["address"]["city"],
                    "addressLine1": buyer["address"]["addressLine1"],
                    "addressLine2": buyer["address"]["addressLine2"],
                    "postalCode": buyer["address"]["postCode"],
                },
                PARAM_CONTACT: {
                    "firstName": buyer["contact"]["firstName"],
                    "lastName": buyer["contact"]["lastName"],
                    "email": buyer["contact"]["email"],
                    "phone": buyer["contact"]["phone"],
                },
            },
        )
        update_order(
            client,
            order["id"],
            parameters=order["parameters"],
        )
        customer_data = get_customer_data(order)
    return order, customer_data


def update_purchase_prices(mpt_client, adobe_client, seller_country, order):
    """
    Creates a preview order in adobe to get the full SKU list to update items prices
    during draft validation.

    Args:
        mpt_client (MPTClient): An instance of the Marketplace platform client.
        adobe_client (AdobeClient): An instance of the Adobe client for communication with the
            Adobe API.
        seller_country (str): Country code of the seller attached to this MPT order.
        order (dict): The MPT order to which the subscription will be added.

    Returns:
        dict: The updated order
    """
    customer_id = get_adobe_customer_id(order) or FAKE_CUSTOMER_ID
    preview_order = adobe_client.create_preview_order(
        seller_country, customer_id, order["id"], order["lines"]
    )

    adobe_skus = [item["offerId"] for item in preview_order["lineItems"]]
    pricelist_id = order["agreement"]["listing"]["priceList"]["id"]
    product_id = order["agreement"]["product"]["id"]
    product_items = get_product_items_by_skus(mpt_client, product_id, adobe_skus)
    pricelist_items = get_pricelist_items_by_product_items(
        mpt_client,
        pricelist_id,
        [product_item["id"] for product_item in product_items],
    )

    product_items_map = {item["id"]: item for item in product_items}
    sku_pricelist_item_map = {
        product_items_map[item["item"]["id"]]["externalIds"]["vendor"]: item
        for item in pricelist_items
    }
    updated_lines = []
    for preview_item in preview_order["lineItems"]:
        order_line = get_order_line_by_sku(order, preview_item["offerId"][:10])
        order_line["price"]["unitPP"] = sku_pricelist_item_map[preview_item["offerId"]]["unitPP"]
        updated_lines.append(order_line)
    order["lines"] = updated_lines

    return order
