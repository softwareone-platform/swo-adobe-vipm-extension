import datetime as dt

from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.adobe.constants import AdobeStatus
from adobe_vipm.adobe.utils import get_item_by_partial_sku
from adobe_vipm.flows.constants import (
    TEMPLATE_SUBSCRIPTION_AUTORENEWAL_DISABLE,
    TEMPLATE_SUBSCRIPTION_AUTORENEWAL_ENABLE,
    TEMPLATE_SUBSCRIPTION_EXPIRED,
)
from adobe_vipm.flows.utils.customer import (
    get_customer_consumables_discount_level,
    get_customer_licenses_discount_level,
)


def get_subscription_by_line_and_item_id(
    subscriptions: list[dict],
    item_id: str,
    line_id: str,
) -> dict | None:
    """
    Return a subscription by line id and sku.

    Args:
        subscriptions: a list of subscription objects.
        item_id: the item SKU
        line_id: the id of the order line that should contain the given SKU.

    Returns:
        The corresponding subscription if it is found, None otherwise.
    """
    for subscription in subscriptions:
        item = find_first(
            lambda x: x["id"] == line_id and x["item"]["id"] == item_id,
            subscription["lines"],
        )

        if item:
            return subscription

    return None


def get_adobe_subscription_id(subscription: dict) -> str | None:
    """
    Return the value of the subscription id from the subscription.

    Args:
        subscription: the subscription object from which extract the adobe subscription id.

    Returns:
        The value of the subscription id parameter if found, None otherwise.
    """
    return subscription.get("externalIds", {}).get("vendor")


def is_transferring_item_expired(item: dict) -> bool:
    """
    Checks if the transferring item is expired.

    Args:
        item: Adobe transfer item.

    Returns:
        True if the item is expired.
    """
    if "status" in item and item["status"] == AdobeStatus.INACTIVE_OR_GENERIC_FAILURE:
        return True

    renewal_date = dt.date.fromisoformat(item["renewalDate"])
    return dt.datetime.now(tz=dt.UTC).date() > renewal_date


def are_all_transferring_items_expired(adobe_items: list[dict]) -> bool:
    """
    Check if all Adobe subscriptions to be transferred are expired.

    Args:
        adobe_items: List of adobe items to be transferred. must be extracted.

    Returns:
        True if all Adobe subscriptions are expired, False otherwise.
    """
    return all(is_transferring_item_expired(item) for item in adobe_items)


def is_line_item_active_subscription(subscriptions: list[dict], line: dict) -> bool:
    """
    Checks that Adobe subscription related to the MPT Order line is active.

    Args:
        subscriptions: list of Adobe subscriptions.
        line: MPT order or Agreement line.

    Returns:
        If Adobe subscription related to the MPT order line is active.
    """
    adobe_item = get_item_by_partial_sku(
        subscriptions["items"], line["item"]["externalIds"]["vendor"]
    )
    return adobe_item["status"] == AdobeStatus.SUBSCRIPTION_ACTIVE


def get_transfer_item_sku_by_subscription(trf: dict, sub_id: str) -> str | None:
    """
    Retrieves item Adobe sku from transfer related to subscription.

    Args:
        trf: Adobe transfer.
        sub_id: Adobe subscription id.

    Returns:
        Adobe offer id
    """
    item = find_first(
        lambda x: x["subscriptionId"] == sub_id,
        trf["lineItems"],
    )
    return item.get("offerId") if item else None


def is_consumables_sku(sku: str) -> bool:
    """
    Checks if Adobe sku is consumable.

    Args:
        sku: Adobe sku.

    Returns:
        If is consumable.
    """
    return sku[10] == "T"


def get_sku_with_discount_level(sku: str, customer: dict) -> str:
    """
    Converts cutted sku (MPT Item sku) to Adobe sku with discount level.

    Args:
        sku: cutted Adobe sku without discount level.
        customer: Adobe customer

    Returns:
        Sku with proper discount level based on Adobe customer's discount level.
    """
    discount_level = (
        get_customer_licenses_discount_level(customer)
        if not is_consumables_sku(sku)
        else get_customer_consumables_discount_level(customer)
    )
    return f"{sku[0:10]}{discount_level}{sku[12:]}"


def get_price_item_by_line_sku(prices: dict, line_sku: str) -> dict | None:
    """
    Retrives price item related to the Adobe sku.

    Args:
        prices: Price items.
        line_sku: Item sku to search for.

    Returns:
        Price item.
    """
    return find_first(
        lambda price_item: price_item[0].startswith(line_sku),
        list(prices.items()),
    )


def get_subscription_by_line_subs_id(subscriptions, line):
    """
    Get the subscription by line subscription id.

    Args:
        subscriptions: The subscriptions of the agreement.
        line: The line of the order.
    """
    subscription = find_first(
        lambda subscription: subscription["id"] == line["subscription"]["id"],
        subscriptions
    )
    return subscription and subscription["externalIds"]["vendor"]


def get_template_name_by_subscription(adobe_subscription):
    """
    Get the template name by subscription.

    Args:
        adobe_subscription: The Adobe subscription.

    Returns:
        The template name.
    """
    if adobe_subscription.get("status") == AdobeStatus.SUBSCRIPTION_TERMINATED:
        return TEMPLATE_SUBSCRIPTION_EXPIRED

    if adobe_subscription.get("autoRenewal", {}).get("enabled"):
        return TEMPLATE_SUBSCRIPTION_AUTORENEWAL_ENABLE
    return TEMPLATE_SUBSCRIPTION_AUTORENEWAL_DISABLE
