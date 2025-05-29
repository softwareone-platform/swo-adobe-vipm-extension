"""
This module contains orders helper functions.
"""

import logging
from datetime import date, timedelta
from operator import itemgetter

from django.conf import settings
from mpt_extension_sdk.mpt_http.mpt import (
    get_agreement,
    get_licensee,
    update_order,
)

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.constants import (
    STATUS_3YC_ACTIVE,
    STATUS_3YC_COMMITTED,
)
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.adobe.utils import get_3yc_commitment, get_item_by_partial_sku
from adobe_vipm.airtable.models import get_prices_for_3yc_skus, get_prices_for_skus
from adobe_vipm.flows.constants import (
    ERR_DOWNSIZE_MINIMUM_3YC_CONSUMABLES,
    ERR_DOWNSIZE_MINIMUM_3YC_GENERIC,
    ERR_DOWNSIZE_MINIMUM_3YC_LICENSES,
    ERR_DOWNSIZE_MINIMUM_3YC_VALIDATION,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
)
from adobe_vipm.flows.fulfillment.shared import switch_order_to_failed
from adobe_vipm.flows.pipeline import Step
from adobe_vipm.flows.utils import (
    get_adobe_customer_id,
    get_adobe_order_id,
    get_customer_data,
    get_due_date,
    get_market_segment,
    get_order_line_by_sku,
    get_price_item_by_line_sku,
    get_retry_count,
    is_consumables_sku,
    map_returnable_to_return_orders,
    reset_order_error,
    reset_ordering_parameters_error,
    set_customer_data,
    set_order_error,
    split_downsizes_upsizes_new,
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
        context.downsize_lines, context.upsize_lines, context.new_lines = (
            split_downsizes_upsizes_new(
                context.order,
            )
        )

        retry_count = get_retry_count(context.order)
        if retry_count and int(retry_count) > 0:
            # when due date parameter is created and new code to process it
            # is released, it may happen
            # that there are order in processing, that don't have
            # due date parameter. If such orders were processed at least once
            # means retry_count is set and it is > 0
            # just setup due date to not to send email, like new order was
            # created
            context.due_date = date.today() + timedelta(
                days=int(settings.EXTENSION_CONFIG.get("DUE_DATE_DAYS"))
            )
        else:
            # usual due date processing for new orders
            # or when order was in processing when due date parameter
            # was added, but extension didn't try to process it still
            # means process it like usual order and send email notification
            context.due_date = get_due_date(context.order)

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
            try:
                context.adobe_customer = adobe_client.get_customer(
                    context.authorization_id,
                    context.adobe_customer_id,
                )
            except AdobeAPIError as e:
                logger.exception(f"{context}: failed to retrieve Adobe customer: {e}")
                return
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
        # Get the 3YC commitment if it is enabled
        commitment = self.get_3yc_commitment_enabled(context.adobe_customer)
        if (
            commitment
            and context.downsize_lines
            and not self.is_return_order_created(context)
        ):
            adobe_client = get_adobe_client()
            # get Adobe customer subscriptions
            subscriptions = adobe_client.get_subscriptions(
                context.authorization_id,
                context.adobe_customer_id,
            )
            count_licenses, count_consumables = self.get_licenses_and_consumables_count(
                subscriptions
            )
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
            error = self.validate_minimum_quantity(
                context, commitment, count_licenses, count_consumables
            )
            if error:
                self.manage_order_error(client, context, error)
                return

        next_step(client, context)

    def manage_order_error(self, client, context, error):
        if self.is_validation:
            context.order = set_order_error(
                context.order,
                ERR_DOWNSIZE_MINIMUM_3YC_VALIDATION.to_dict(error=error),
            )
        else:
            switch_order_to_failed(
                client,
                context.order,
                ERR_DOWNSIZE_MINIMUM_3YC_VALIDATION.to_dict(error=error),
            )

    @staticmethod
    def get_licenses_and_consumables_count(subscriptions):
        """
        Get the count of licenses and consumables from the Adobe customer subscriptions.
        Args:
            subscriptions (dict): Adobe customer subscriptions.
        Returns:
            tuple: The count of licenses and consumables.

        """
        count_licenses = 0
        count_consumables = 0
        for subscription in subscriptions["items"]:
            if is_consumables_sku(subscription["offerId"]):
                count_consumables += subscription["currentQuantity"]
            else:
                count_licenses += subscription["currentQuantity"]

        return count_licenses, count_consumables

    @staticmethod
    def validate_minimum_quantity(
        context,
        commitment,
        count_licenses,
        count_consumables,
    ):
        is_invalid_license_minimum = False
        is_invalid_consumable_minimum = False
        minimum_licenses = 0
        minimum_consumables = 0

        for mq in commitment["minimumQuantities"]:
            if mq["offerType"] == "LICENSE" and count_licenses < mq["quantity"]:
                is_invalid_license_minimum = True
                minimum_licenses = mq["quantity"]
            if mq["offerType"] == "CONSUMABLES" and count_consumables < mq["quantity"]:
                is_invalid_consumable_minimum = True
                minimum_consumables = mq["quantity"]

        if is_invalid_consumable_minimum and is_invalid_license_minimum:
            logger.error(
                f"{context}: failed due to reduction quantity is not allowed below "
                f"the minimum commitment of licenses and consumables"
            )
            return ERR_DOWNSIZE_MINIMUM_3YC_GENERIC.format(
                minimum_licenses=minimum_licenses,
                minimum_consumables=minimum_consumables,
            )

        if is_invalid_license_minimum:
            logger.error(
                f"{context}: failed due to reduction quantity is not allowed below "
                f"the minimum commitment of licenses"
            )
            return ERR_DOWNSIZE_MINIMUM_3YC_LICENSES.format(
                minimum_licenses=minimum_licenses
            )

        if is_invalid_consumable_minimum:
            logger.error(
                f"{context}: failed due to reduction quantity is not allowed below"
                f" the minimum commitment of consumables"
            )
            return ERR_DOWNSIZE_MINIMUM_3YC_CONSUMABLES.format(
                minimum_consumables=minimum_consumables
            )

    @staticmethod
    def get_3yc_commitment_enabled(adobe_customer):
        """
        Get the 3YC commitment if it is enabled.
        Args:
            adobe_customer (dict): Adobe customer object.

        Returns: Commitment object if it is enabled, otherwise None.

        """
        commitment = get_3yc_commitment(adobe_customer)

        if (
            commitment
            and commitment["status"] in (STATUS_3YC_COMMITTED, STATUS_3YC_ACTIVE)
            and date.today() <= date.fromisoformat(commitment["endDate"])
        ):
            return commitment
        return None

    @staticmethod
    def is_return_order_created(context):
        for sku, returnable_orders in context.adobe_returnable_orders.items():
            return_orders = context.adobe_return_orders.get(sku, [])
            for _returnable_order, return_order in map_returnable_to_return_orders(
                returnable_orders or [], return_orders
            ):
                if return_order:
                    return True
        return False


class UpdatePrices(Step):
    def __call__(self, client, context, next_step):
        if not (context.adobe_new_order or context.adobe_preview_order):
            next_step(client, context)
            return

        actual_skus = self._get_actual_skus(context)
        prices = self._get_prices_for_skus(context, actual_skus)
        updated_lines = self._create_updated_lines(context, actual_skus, prices)
        self._update_order(client, context, updated_lines)

        next_step(client, context)

    def _get_actual_skus(self, context):
        """Extract SKUs from either new order or preview order."""
        order_data = context.adobe_new_order or context.adobe_preview_order
        return [item["offerId"] for item in order_data["lineItems"]]

    def _get_prices_for_skus(self, context, actual_skus):
        """Get prices for SKUs considering 3YC commitment if applicable."""
        commitment = get_3yc_commitment(context.adobe_customer) if context.adobe_customer else None

        if self._is_valid_3yc_commitment(commitment):
            return get_prices_for_3yc_skus(
                context.product_id,
                context.currency,
                date.fromisoformat(commitment["startDate"]),
                actual_skus,
            )
        return get_prices_for_skus(
            context.product_id,
            context.currency,
            actual_skus
        )

    def _is_valid_3yc_commitment(self, commitment):
        """Check if 3YC commitment is valid and active."""
        if not commitment:
            return False

        return (
            commitment["status"] in (STATUS_3YC_COMMITTED, STATUS_3YC_ACTIVE)
            and date.fromisoformat(commitment["endDate"]) >= date.today()
        )

    def _create_updated_lines(self, context, actual_skus, prices):
        """Create updated order lines with new prices."""
        updated_lines = []

        # Update lines for actual SKUs
        for sku in actual_skus:
            line = get_order_line_by_sku(context.order, sku)
            new_price_item = get_price_item_by_line_sku(
                prices,
                line["item"]["externalIds"]["vendor"]
            )
            updated_lines.append({
                "id": line["id"],
                "price": {"unitPP": new_price_item[1]},
            })

        # Add remaining lines with unchanged prices
        updated_lines_ids = {line["id"] for line in updated_lines}
        for line in context.order["lines"]:
            if line["id"] not in updated_lines_ids:
                updated_lines.append({
                    "id": line["id"],
                    "price": {"unitPP": line["price"]["unitPP"]},
                })

        return sorted(updated_lines, key=itemgetter("id"))

    def _update_order(self, client, context, lines):
        """Update the order with new prices."""
        update_order(client, context.order_id, lines=lines)
        logger.info(f"{context}: order lines prices updated successfully")
