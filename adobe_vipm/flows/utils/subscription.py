from datetime import date

from adobe_vipm.adobe.constants import (
    STATUS_INACTIVE_OR_GENERIC_FAILURE,
    STATUS_SUBSCRIPTION_ACTIVE,
)
from adobe_vipm.adobe.utils import get_item_by_partial_sku
from adobe_vipm.flows.utils.customer import (
    get_customer_consumables_discount_level,
    get_customer_licenses_discount_level,
)
from adobe_vipm.utils import find_first


def get_subscription_by_line_and_item_id(subscriptions, item_id, line_id):
    """
    Return a subscription by line id and sku.

    Args:
        subscriptions (list): a list of subscription objects.
        item_id (str): the item SKU
        line_id (str): the id of the order line that should contain the given SKU.

    Returns:
        dict: the corresponding subscription if it is found, None otherwise.
    """
    for subscription in subscriptions:
        item = find_first(
            lambda x: x["id"] == line_id and x["item"]["id"] == item_id,
            subscription["lines"],
        )

        if item:
            return subscription


def get_adobe_subscription_id(subscription):
    """
    Return the value of the subscription id from the subscription.

    Args:
        subscription (dict): the subscription object from which extract
        the adobe subscription id.
    Returns:
        str: the value of the subscription id parameter if found, None otherwise.
    """
    return subscription.get("externalIds", {}).get("vendor")


def is_transferring_item_expired(item):
    if "status" in item and item["status"] == STATUS_INACTIVE_OR_GENERIC_FAILURE:
        return True

    renewal_date = date.fromisoformat(item["renewalDate"])
    return date.today() > renewal_date


def are_all_transferring_items_expired(adobe_items):
    """
    Check if all Adobe subscriptions to be transferred are expired.
    Args:
        adobe_items (list): List of adobe items to be transferred.
        must be extracted.

    Returns:
        bool: True if all Adobe subscriptions are expired, False otherwise.
    """
    return all(is_transferring_item_expired(item) for item in adobe_items)


def is_line_item_active_subscription(subscriptions, line):
    adobe_item = get_item_by_partial_sku(
        subscriptions["items"], line["item"]["externalIds"]["vendor"]
    )
    return adobe_item["status"] == STATUS_SUBSCRIPTION_ACTIVE


def get_transfer_item_sku_by_subscription(trf, sub_id):
    item = find_first(
        lambda x: x["subscriptionId"] == sub_id,
        trf["lineItems"],
    )
    return item.get("offerId") if item else None


def is_consumables_sku(sku):
    return sku[10] == "T"


def get_sku_with_discount_level(sku, customer):
    discount_level = (
        get_customer_licenses_discount_level(customer)
        if not is_consumables_sku(sku)
        else get_customer_consumables_discount_level(customer)
    )
    sku_with_discount = f"{sku[0:10]}{discount_level}{sku[12:]}"
    return sku_with_discount


def get_price_item_by_line_sku(prices, line_sku):
    return find_first(
        lambda price_item: price_item[0].startswith(line_sku),
        list(prices.items()),
    )
