import copy
import functools

from mpt_extension_sdk.mpt_http.mpt import (
    get_product_items_by_skus,
    get_product_onetime_items_by_ids,
)
from mpt_extension_sdk.mpt_http.utils import find_first

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.errors import AdobeAPIError, AdobeHttpError
from adobe_vipm.flows.constants import (
    ERR_ADOBE_MEMBERSHIP_ID,
    ERR_ADOBE_MEMBERSHIP_ID_EMPTY,
    ERR_ADOBE_MEMBERSHIP_ID_ITEM,
    ERR_ADOBE_MEMBERSHIP_NOT_FOUND,
    ERR_ADOBE_UNEXPECTED_ERROR,
    ERR_UPDATING_TRANSFER_ITEMS,
    ORDER_TYPE_CHANGE,
    ORDER_TYPE_CONFIGURATION,
    ORDER_TYPE_PURCHASE,
    ORDER_TYPE_TERMINATION,
    Param,
)
from adobe_vipm.flows.utils import (
    get_ordering_parameter,
    is_migrate_customer,
    set_ordering_parameter_error,
)
from adobe_vipm.flows.utils.customer import is_new_customer
from adobe_vipm.flows.utils.parameter import get_adobe_membership_id
from adobe_vipm.flows.utils.subscription import (
    are_all_transferring_items_expired,
    is_transferring_item_expired,
)
from adobe_vipm.flows.validation.transfer import get_prices
from adobe_vipm.utils import get_3yc_commitment, get_partial_sku


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


def validate_transfer_not_migrated(mpt_client, order: dict) -> tuple[bool, dict]:
    """
    Validates a transfer that has not been already migrated by the mass migration tool.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        order: The order to validate.

    Returns:
        (True, order) if there is a validation error, (False, order) otherwise.
    """
    authorization_id = order["authorization"]["id"]
    membership_id = get_adobe_membership_id(order)
    transfer_preview = None

    try:
        adobe_client = get_adobe_client()
        transfer_preview = adobe_client.preview_transfer(
            authorization_id,
            membership_id,
        )
    except AdobeAPIError as e:
        param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
        order = set_ordering_parameter_error(
            order,
            Param.MEMBERSHIP_ID.value,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=str(e)),
        )
        return True, order
    except AdobeHttpError as he:
        err_msg = (
            ERR_ADOBE_MEMBERSHIP_NOT_FOUND if he.status_code == 404 else ERR_ADOBE_UNEXPECTED_ERROR
        )
        param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
        order = set_ordering_parameter_error(
            order,
            Param.MEMBERSHIP_ID.value,
            ERR_ADOBE_MEMBERSHIP_ID.to_dict(title=param["name"], details=err_msg),
        )
        return True, order
    commitment = get_3yc_commitment(transfer_preview)
    return add_lines_to_order(mpt_client, order, transfer_preview["items"], commitment, "quantity")


def add_lines_to_order(
    mpt_client,
    order: dict,
    adobe_items: list[dict],
    commitment: dict,
    quantity_field: str,
    *,
    is_transferred=False,
) -> tuple[bool, dict]:
    """
    Add the lines that belongs to the provided Adobe VIP membership to the current order.

    Updates the purchase price of each line according to the customer discount level/benefits.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        order: The order to validate.
        adobe_items: List of Adobe subscriptions to be migrated.
        commitment: Either the customer 3y commitment data or None if the customer doesn't
        have such benefit.
        quantity_field: The name of the field that contains the quantity depending on the
        provided `adobe_object` argument.
        is_transferred: True if the order has already been transferred, False otherwise.

    Returns:
        (True, order) if there is an error adding the lines, (False, order) otherwise.
    """
    order_error = False
    items = []

    if adobe_items:
        items = _get_items(adobe_items, mpt_client, order)
        if is_transferred:
            if are_all_transferring_items_expired(adobe_items):
                # If the order already has items and all the items on Adobe to be migrated are
                # expired, the user can add, edit or delete the expired subscriptions
                if len(order["lines"]):
                    return False, order

            else:
                adobe_items, order, order_error = _fail_validation_if_items_updated(
                    adobe_items,
                    order,
                    quantity_field,
                    order_error=order_error,
                )
        else:
            adobe_items = [item for item in adobe_items if not is_transferring_item_expired(item)]

    if not adobe_items:
        return _handle_empty_adobe_items(order)

    order_error, order = _get_updated_order_lines(
        adobe_items,
        commitment,
        items,
        order,
        quantity_field,
        order_error=order_error,
    )

    return order_error, order


def _handle_empty_adobe_items(order: dict) -> tuple[bool, dict]:
    if is_migrate_customer(order):
        order = set_ordering_parameter_error(
            order,
            Param.MEMBERSHIP_ID.value,
            ERR_ADOBE_MEMBERSHIP_ID_EMPTY.to_dict(),
        )
    return True, order


def _get_updated_order_lines(
    adobe_items: list[dict],
    commitment: dict,
    items: list[dict],
    order: dict,
    quantity_field: str,
    *,
    order_error: bool,
) -> tuple[bool, dict]:
    valid_skus = [get_partial_sku(item["offerId"]) for item in adobe_items]
    returned_full_skus = [item["offerId"] for item in adobe_items]
    prices = get_prices(order, commitment, returned_full_skus)
    items_map = {
        item["externalIds"]["vendor"]: item
        for item in items
        if item["externalIds"]["vendor"] in valid_skus
    }

    return _update_order_lines(
        order,
        adobe_items,
        prices,
        items_map,
        quantity_field,
        valid_skus,
        order_error=order_error,
    )


def _fail_validation_if_items_updated(
    adobe_items: list[dict],
    order: dict,
    quantity_field: str,
    *,
    order_error: bool,
) -> tuple[list[dict], dict, bool]:
    # remove expired items from adobe items
    non_expired_items = [item for item in adobe_items if not is_transferring_item_expired(item)]
    # If the order items has been updated, the validation order will fail
    if len(order["lines"]) and has_order_line_updated(
        order["lines"], non_expired_items, quantity_field
    ):
        order_error = True
        order = set_order_error(order, ERR_UPDATING_TRANSFER_ITEMS.to_dict())

    return non_expired_items, order, order_error


def _get_items(
    adobe_items: list[dict],
    mpt_client,
    order: dict,
) -> dict[str, dict]:
    returned_skus = [get_partial_sku(item["offerId"]) for item in adobe_items]

    return get_product_items_by_skus(mpt_client, order["agreement"]["product"]["id"], returned_skus)


def _update_order_lines(
    order: dict,
    adobe_items: list[dict],
    prices: dict[str, float],
    items_map: dict[str, dict],
    quantity_field: str,
    returned_skus: list[str],
    *,
    order_error: bool,  # TODO: that's a really strange parameter, you pass it down and return back
) -> tuple[bool, dict]:
    for adobe_line in adobe_items:
        item = items_map.get(get_partial_sku(adobe_line["offerId"]))
        if not item:
            param = get_ordering_parameter(order, Param.MEMBERSHIP_ID.value)
            order = set_ordering_parameter_error(
                order,
                Param.MEMBERSHIP_ID.value,
                ERR_ADOBE_MEMBERSHIP_ID_ITEM.to_dict(
                    title=param["name"],
                    item_sku=get_partial_sku(adobe_line["offerId"]),
                ),
            )
            order_error = True

            return order_error, order

        current_line = get_order_line_by_sku(order, get_partial_sku(adobe_line["offerId"]))
        if current_line:
            current_line["quantity"] = adobe_line[quantity_field]
        else:
            new_line = {
                "item": item,
                "quantity": adobe_line[quantity_field],
                "oldQuantity": 0,
            }
            new_line.setdefault("price", {})
            new_line["price"]["unitPP"] = prices.get(adobe_line["offerId"], 0)
            order["lines"].append(new_line)

    lines = [
        line for line in order["lines"] if line["item"]["externalIds"]["vendor"] in returned_skus
    ]
    order["lines"] = lines

    return order_error, order
