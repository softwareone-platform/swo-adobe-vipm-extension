import copy
import functools

from mpt_extension_sdk.mpt_http.mpt import get_product_onetime_items_by_ids
from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.flows.constants import (
    ORDER_TYPE_CHANGE,
    ORDER_TYPE_CONFIGURATION,
    ORDER_TYPE_PURCHASE,
    ORDER_TYPE_TERMINATION,
)
from adobe_vipm.flows.utils.customer import is_new_customer
from adobe_vipm.utils import get_partial_sku


def get_adobe_order_id(order: dict) -> str | None:
    """
    Retrieve the Adobe order identifier from the order vendor external id.

    Args:
        order: The order from which the Adobe order id should be retrieved.

    Returns:
        The Adobe order identifier or None if it is not set.
    """
    return order.get("externalIds", {}).get("vendor")


def set_adobe_order_id(order: dict, adobe_order_id: str) -> dict:
    """
    Set Adobe order identifier as the order vendor external id attribute.

    Args:
        order: The order for which the Adobe order id should be set.
        adobe_order_id: Adobe order id.

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    updated_order["externalIds"] = updated_order.get("externalIds", {}) | {"vendor": adobe_order_id}
    return updated_order


def is_purchase_order(order: dict) -> bool:
    """
    Check if the order is a real purchase order or a subscriptions transfer order.

    Args:
        order: The order to check.

    Returns:
        True if it is a real purchase order, False otherwise.
    """
    return order["type"] == ORDER_TYPE_PURCHASE and is_new_customer(order)


def is_transfer_order(order: dict) -> bool:
    """
    Check if the order is a subscriptions transfer order.

    Args:
        order: The order to check.

    Returns:
        True if it is a subscriptions transfer order, False otherwise.
    """
    return order["type"] == ORDER_TYPE_PURCHASE and not is_new_customer(order)


def is_change_order(order: dict) -> bool:
    """
    Cheks if it is a change MPT order.

    Args:
        order: MPT order.

    Returns:
        True if MPT order has type Change.
    """
    return order["type"] == ORDER_TYPE_CHANGE


def is_termination_order(order: dict) -> bool:
    """
    Cheks if it is a termination MPT order.

    Args:
        order: MPT order.

    Returns:
        True if MPT order has type Terminate.
    """
    return order["type"] == ORDER_TYPE_TERMINATION


def is_configuration_order(order: dict) -> bool:
    """
    Cheks if it is a configuration MPT order.

    Args:
        order: MPT order.

    Returns:
        True if MPT order has type Configuration.
    """
    return order["type"] == ORDER_TYPE_CONFIGURATION


def split_downsizes_upsizes_new(order: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Splits MPT order lines to lines that are dowsizes, upsizes and net new.

    Args:
        order: The order which lines must be split.

    Returns:
        A tuple where the first element is a list of items to downsize, the second
        a list of items to upsize and third is a list of new lines.
    """
    downsize_lines, upsize_lines, new_lines = [], [], []

    for line in order["lines"]:
        if line["quantity"] < line["oldQuantity"]:
            downsize_lines.append(line)
        elif line["oldQuantity"] and line["oldQuantity"] > 0:
            upsize_lines.append(line)
        else:
            new_lines.append(line)

    return downsize_lines, upsize_lines, new_lines


def get_order_line_by_sku(order: dict, sku: str) -> dict | None:
    """
    Returns an order line object by sku or None if not found.

    Args:
        order: The order from which the line must be retrieved.
        sku: Full Adobe Item SKU, including discount level

    Returns:
        The line object or None if not found.
    """
    # important to have `in` here, since line items contain cut Adobe Item SKU
    # and sku is a full Adobe Item SKU including discount level
    return find_first(
        lambda line: line["item"]["externalIds"]["vendor"] in sku,
        order["lines"],
    )


def has_order_line_updated(
    order_lines: list[dict],
    adobe_items: list[dict],
    quantity_field: str,
) -> bool:
    """
    Compare order lines and Adobe items to be transferred.

    Args:
        order_lines: List of order lines
        adobe_items: List of adobe items to be transferred.
        quantity_field: The name of the field that contains the quantity depending on the
        provided `adobe_object` argument.

    Returns:
        True if order line is not equal to adobe items, False otherwise.
    """
    order_line_map = {
        order_line["item"]["externalIds"]["vendor"]: order_line["quantity"]
        for order_line in order_lines
    }

    adobe_items_map = {
        get_partial_sku(adobe_item["offerId"]): adobe_item[quantity_field]
        for adobe_item in adobe_items
    }
    return order_line_map != adobe_items_map


def set_order_error(order: dict, error: dict) -> dict:
    """
    Sets error in MPT order.

    Args:
        order: MPT order.
        error: error (id, message).

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    updated_order["error"] = error
    return updated_order


def reset_order_error(order: dict) -> dict:
    """
    Resets error in MPT order.

    Args:
        order: MPT order.

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    updated_order["error"] = None
    return updated_order


def set_template(order: dict, template: dict) -> dict:
    """
    Sets template in MPT order.

    Args:
        order: MPT order.
        template: MPT tempate to setup. Contains id property

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    updated_order["template"] = template
    return updated_order


def get_one_time_skus(client, order: dict) -> list[str]:
    """
    Get tge SKUs from the order lines that correspond to One-Time items.

    Args:
        client (MPTClient): The client to consume the MPT API.
        order: The order from which the One-Time items SKUs must be extracted.

    Returns:
        List of One-Time SKUs.
    """
    one_time_items = get_product_onetime_items_by_ids(
        client,
        order["agreement"]["product"]["id"],
        [line["item"]["id"] for line in order["lines"]],
    )
    return [item["externalIds"]["vendor"] for item in one_time_items]


def map_returnable_to_return_orders(returnable_orders: list, return_orders: list) -> dict:
    """
    Maps Adobe returnable orders to Adobe return order.

    Args:
        returnable_orders: Adobe returnable orders.
        return_orders: Adobe return orders.

    Returns:
        Mapping returnable order to return order
    """
    mapped = []

    def filter_by_reference_order(reference_order_id, item):
        return item["referenceOrderId"] == reference_order_id

    for returnable_order in returnable_orders:
        return_order = find_first(
            functools.partial(filter_by_reference_order, returnable_order.order["orderId"]),
            return_orders,
        )
        mapped.append((returnable_order, return_order))

    return mapped
