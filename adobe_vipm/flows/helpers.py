"""
This module contains orders helper functions.
"""

import logging
from datetime import date

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import STATUS_3YC_ACTIVE, STATUS_3YC_COMMITTED
from adobe_vipm.adobe.utils import get_3yc_commitment, get_item_by_partial_sku
from adobe_vipm.flows.constants import (
    ERR_DOWNSIZE_MINIMUN_3YC_CONSUMABLES,
    ERR_DOWNSIZE_MINIMUN_3YC_GENERIC,
    ERR_DOWNSIZE_MINIMUN_3YC_LICENSES,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
)
from adobe_vipm.flows.fulfillment.shared import switch_order_to_failed
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
    is_consumables_sku,
    reset_order_error,
    reset_ordering_parameters_error,
    set_customer_data,
    set_order_error,
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
        context.order["agreement"] = get_agreement(
            client, context.order["agreement"]["id"]
        )
        context.order["agreement"]["licensee"] = get_licensee(
            client, context.order["agreement"]["licensee"]["id"]
        )
        context.downsize_lines, context.upsize_lines = split_downsizes_and_upsizes(
            context.order
        )
        context.current_attempt = get_retry_count(context.order)
        context.order_id = context.order["id"]
        context.type = context.order["type"]
        context.agreement_id = context.order["agreement"]["id"]
        context.authorization_id = context.order["authorization"]["id"]
        context.product_id = context.order["agreement"]["product"]["id"]
        context.seller_id = context.order["agreement"]["seller"]["id"]
        context.currency = context.order["agreement"]["listing"]["priceList"][
            "currency"
        ]
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


class ValidateDownsizes3YC:
    """
    Validates If the Adobe customer has a 3YC commitment and the reduction quantity
    is not allowed below the minimum commitment of licenses and consumables.
    """

    def __init__(self, is_validation=False):
        self.is_validation = is_validation

    def __call__(self, client, context, next_step):

        # Check if the Adobe customer has a 3YC commitment
        commitment = get_3yc_commitment(context.adobe_customer)

        if (
            commitment
            and commitment["status"] in (STATUS_3YC_COMMITTED, STATUS_3YC_ACTIVE)
            and date.today() <= date.fromisoformat(commitment["endDate"])
            and context.downsize_lines
        ):
            adobe_client = get_adobe_client()
            # get Adobe customer subscriptions
            subscriptions = adobe_client.get_subscriptions(
                context.authorization_id,
                context.adobe_customer_id,
            )
            count_licenses = 0
            count_consumables = 0
            for subscription in subscriptions["items"]:
                if is_consumables_sku(subscription["offerId"]):
                    count_consumables += subscription["currentQuantity"]
                else:
                    count_licenses += subscription["currentQuantity"]

            for line in context.downsize_lines:
                adobe_item = get_item_by_partial_sku(
                    subscriptions["items"], line["item"]["externalIds"]["vendor"]
                )
                if not adobe_item:
                    self.manage_order_error(
                        client,
                        context,
                        f"Item {line['item']['externalIds']['vendor']} not found "
                        f"in Adobe subscriptions",
                    )
                    return
                delta = line["oldQuantity"] - line["quantity"]
                if is_consumables_sku(adobe_item["offerId"]):
                    count_consumables -= delta
                else:
                    count_licenses -= delta

            is_invalid_license_minimum = False
            is_invalid_consumable_minimum = False
            minimum_licenses = 0
            minimum_consumables = 0

            for mq in commitment["minimumQuantities"]:
                if mq["offerType"] == "LICENSE":
                    if count_licenses < mq["quantity"]:
                        is_invalid_license_minimum = True
                        minimum_licenses = mq["quantity"]
                if mq["offerType"] == "CONSUMABLES":
                    if count_consumables < mq["quantity"]:
                        is_invalid_consumable_minimum = True
                        minimum_consumables = mq["quantity"]

            if is_invalid_consumable_minimum and is_invalid_license_minimum:
                self.manage_order_error(
                    client,
                    context,
                    ERR_DOWNSIZE_MINIMUN_3YC_GENERIC.format(
                        minimum_licenses=minimum_licenses,
                        minimun_consumables=minimum_consumables,
                    ),
                )
                logger.error(
                    f"{context}: failed due to reduction quantity is not allowed below "
                    f"the minimum commitment of licenses and consumables"
                )
                return

            if is_invalid_license_minimum:
                self.manage_order_error(
                    client,
                    context,
                    ERR_DOWNSIZE_MINIMUN_3YC_LICENSES.format(
                        minimum_licenses=minimum_licenses
                    ),
                )
                logger.error(
                    f"{context}: failed due to reduction quantity is not allowed below "
                    f"the minimum commitment of licenses"
                )
                return

            if is_invalid_consumable_minimum:
                self.manage_order_error(
                    client,
                    context,
                    ERR_DOWNSIZE_MINIMUN_3YC_CONSUMABLES.format(
                        minimun_consumables=minimum_consumables
                    ),
                )
                logger.error(
                    f"{context}: failed due to reduction quantity is not allowed below"
                    f" the minimum commitment of consumables"
                )
                return

        next_step(client, context)

    def manage_order_error(self, client, context, error):
        if self.is_validation:
            context.order = set_order_error(
                context.order,
                error,
            )
        else:
            switch_order_to_failed(
                client,
                context.order,
                error,
            )
