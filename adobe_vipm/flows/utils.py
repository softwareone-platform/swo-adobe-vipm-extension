import copy
import functools
from datetime import UTC, datetime

from adobe_vipm.adobe.utils import to_adobe_line_id
from adobe_vipm.flows.constants import (
    CANCELLATION_WINDOW_DAYS,
    OPTIONAL_CUSTOMER_ORDER_PARAMS,
    ORDER_TYPE_CHANGE,
    ORDER_TYPE_PURCHASE,
    ORDER_TYPE_TERMINATION,
    PARAM_3YC,
    PARAM_3YC_CONSUMABLES,
    PARAM_3YC_ENROLL_STATUS,
    PARAM_3YC_LICENSES,
    PARAM_ADDRESS,
    PARAM_AGREEMENT_TYPE,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_CUSTOMER_ID,
    PARAM_MEMBERSHIP_ID,
    PARAM_PHASE_FULFILLMENT,
    PARAM_PHASE_ORDERING,
    PARAM_PREFERRED_LANGUAGE,
    PARAM_RETRY_COUNT,
)
from adobe_vipm.flows.dataclasses import ItemGroups
from adobe_vipm.utils import find_first


def get_parameter(parameter_phase, source, param_external_id):
    """
    Returns a parameter of a given phase by its external identifier.
    Returns an empty dictionary if the parameter is not found.
    Args:
        parameter_phase (str): The phase of the parameter (ordering, fulfillment).
        source (str): The source business object from which the parameter
        should be extracted.
        param_external_id (str): The unique external identifier of the parameter.

    Returns:
        dict: The parameter object or an empty dictionary if not found.
    """
    return find_first(
        lambda x: x["externalId"] == param_external_id,
        source["parameters"][parameter_phase],
        default={},
    )


get_ordering_parameter = functools.partial(get_parameter, PARAM_PHASE_ORDERING)

get_fulfillment_parameter = functools.partial(get_parameter, PARAM_PHASE_FULFILLMENT)


def get_adobe_membership_id(source):
    """
    Get the Adobe membership identifier from the correspoding ordering
    parameter or None if it is not set.

    Args:
        source (dict): The business object from which the membership id
        should be retrieved.

    Returns:
        str: The Adobe membership identifier or None if it isn't set.
    """
    return get_ordering_parameter(
        source,
        PARAM_MEMBERSHIP_ID,
    ).get("value")


def is_purchase_order(order):
    """
    Check if the order is a real purchase order or a subscriptions transfer order.
    Subscriptions transfer orders have an ordering parameter filled with the
    Adobe membership identifier that must be migrated.
    Args:
        source (str): The order to check.

    Returns:
        bool: True if it is a real purchase order, False otherwise.
    """
    return order["type"] == ORDER_TYPE_PURCHASE and not get_adobe_membership_id(order)


def is_transfer_order(order):
    """
    Check if the order is a subscriptions transfer order.
    Subscriptions transfer orders are purchase orders that have an ordering parameter filled with
    the Adobe membership identifier that must be migrated.
    Args:
        source (str): The order to check.

    Returns:
        bool: True if it is a subscriptions transfer order, False otherwise.
    """
    return order["type"] == ORDER_TYPE_PURCHASE and get_adobe_membership_id(order)


def is_change_order(order):
    return order["type"] == ORDER_TYPE_CHANGE


def is_termination_order(order):
    return order["type"] == ORDER_TYPE_TERMINATION


def get_adobe_customer_id(source):
    """
    Get the Adobe customer identifier from the correspoding fulfillment
    parameter or None if it is not set.

    Args:
        source (dict): The business object from which the customer id
        should be retrieved.

    Returns:
        str: The Adobe customer identifier or None if it isn't set.
    """
    return get_fulfillment_parameter(
        source,
        PARAM_CUSTOMER_ID,
    ).get("value")


def set_adobe_customer_id(order, customer_id):
    """
    Create a copy of the order. Set the CustomerId
    fulfillment parameter on the copy of the original order.
    Return the copy of the original order with the
    CustomerId parameter filled.
    """
    updated_order = copy.deepcopy(order)
    customer_ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_CUSTOMER_ID,
    )
    customer_ff_param["value"] = customer_id
    return updated_order


def get_adobe_order_id(order):
    """
    Retrieve the Adobe order identifier from the order vendor external id.

    Args:
        order (dict): The order from which the Adobe order id should
        be retrieved.

    Returns:
        str: The Adobe order identifier or None if it is not set.
    """
    return order.get("externalIds", {}).get("vendor")


def set_adobe_order_id(order, adobe_order_id):
    """
    Set Adobe order identifier as the order vendor external id attribute.

    Args:
        order (dict): The order for which the Adobe order id should
        be set.

    Returns:
        dict: The updated order with the vendor external id attribute set.
    """
    updated_order = copy.deepcopy(order)
    updated_order["externalIds"] = updated_order.get("externalIds", {}) | {
        "vendor": adobe_order_id
    }
    return updated_order


def get_customer_data(order):
    """
    Returns a dictionary with the customer data extracted from the
    corresponding ordering parameters.

    Args:
        order (dict): The order from which the customer data must be
        retrieved.

    Returns:
        dict: A dictionary with the customer data.
    """
    customer_data = {}
    for param_external_id in (
        PARAM_COMPANY_NAME,
        PARAM_PREFERRED_LANGUAGE,
        PARAM_ADDRESS,
        PARAM_CONTACT,
        PARAM_3YC,
        PARAM_3YC_CONSUMABLES,
        PARAM_3YC_LICENSES,
    ):
        customer_data[param_external_id] = get_ordering_parameter(
            order,
            param_external_id,
        ).get("value")

    return customer_data


def set_customer_data(order, customer_data):
    """
    Set the ordering parameters with the customer data.

    Args:
        order (dict): The order for which the parameters must be set.
        customer_data (dict): the customer data that must be set

    Returns:
        dict: The order updated with the ordering parameters for customer data.
    """
    updated_order = copy.deepcopy(order)
    for param_external_id, value in customer_data.items():
        get_ordering_parameter(
            updated_order,
            param_external_id,
        )["value"] = value
    return updated_order


def set_ordering_parameter_error(order, param_external_id, error):
    """
    Set a validation error on an ordering parameter.

    Args:
        order (dict): The order that contains the parameter.
        param_external_id (str): The external identifier of the parameter.
        error (dict): The error (id, message) that must be set.

    Returns:
        dict: The order updated.
    """
    updated_order = copy.deepcopy(order)
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["error"] = error
    param["constraints"] = {
        "hidden": False,
        "optional": False,
    }
    return updated_order


def reset_ordering_parameters_error(order):
    """
    Reset errors for all ordering parameters

    Args:
        order (dict): The order that contains the parameter.

    Returns:
        dict: The order updated.
    """
    updated_order = copy.deepcopy(order)

    for param in updated_order["parameters"][PARAM_PHASE_ORDERING]:
        param["error"] = None

    return updated_order


def get_order_line(order, line_id):
    """
    Returns an order line object by the line identifier
    or None if not found.

    Args:
        order (dict): The order from which the line
        must be retrieved.
        line_id (str): The idetifier of the line.

    Returns:
        dict: The line object or None if not found.
    """
    return find_first(
        lambda line: line_id == to_adobe_line_id(line["id"]),
        order["lines"],
    )


def get_order_line_by_sku(order, sku):
    """
    Returns an order line object by sku or None if not found.

    Args:
        order (dict): The order from which the line
        must be retrieved.
        sku (str): Full Adobe Item SKU, including discount level

    Returns:
        dict: The line object or None if not found.
    """
    # important to have `in` here, since line items contain cutted Adobe Item SKU
    # and sku is a full Adobe Item SKU including discount level
    return find_first(
        lambda line: line["item"]["externalIds"]["vendor"] in sku,
        order["lines"],
    )


def get_price_item_by_line_sku(price_items, line_sku):
    return find_first(
        lambda price_item: line_sku in price_item["item"]["externalIds"]["vendor"],
        price_items,
    )


def increment_retry_count(order):
    """
    Increment the retry count fulfillment parameter by 1 if it exists
    or set it to 1 if not found.

    Args:
        order (dict): The order that containts the retry count fulfillment
        parameter.

    Returns:
        dict: The updated order.
    """
    updated_order = copy.deepcopy(order)
    param = get_fulfillment_parameter(
        updated_order,
        PARAM_RETRY_COUNT,
    )

    param["value"] = str(int(param["value"]) + 1) if param["value"] else "1"
    return updated_order


def reset_retry_count(order):
    """
    Reset the retry count fulfillment parameter to 0.

    Args:
        order (dict): The order that containts the retry count fulfillment
        parameter.

    Returns:
        dict: The updated order.
    """
    updated_order = copy.deepcopy(order)
    param = get_fulfillment_parameter(
        updated_order,
        PARAM_RETRY_COUNT,
    )
    param["value"] = "0"
    return updated_order


def get_retry_count(order):
    """
    Returns the value of the retry count fulfillment parameter.

    Args:
        order (dict): The order that containts the retry count fulfillment
        parameter.

    Returns:
        int: The value of the retry count parameter.
    """
    return int(
        get_fulfillment_parameter(
            order,
            PARAM_RETRY_COUNT,
        ).get("value", "0")
        or "0",
    )


def get_subscription_by_line_and_item_id(subscriptions, item_id, line_id):
    """
    Return a subscription by line id and sku.

    Args:
        subscriptions (list): a list of subscription obects.
        vendor_external_id (str): the item SKU
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


def in_cancellation_window(order, line):
    """
    Checks if the creation date of a subscription item
    is within the cancellation window.

    Args:
        order (dict): The change order is being processed.
        line (dict): the order line that should be checked.

    Returns:
        bool: True is the subscription items is within the
        cancellation window or the subscription does not exist
        (purchase cases), False otherwise.
    """
    subscription = get_subscription_by_line_and_item_id(
        order["subscriptions"],
        line["item"]["id"],
        line["id"],
    )
    if not subscription:
        return True

    creation_date = datetime.fromisoformat(subscription["startDate"])
    delta = datetime.now(UTC) - creation_date
    return delta.days < CANCELLATION_WINDOW_DAYS


def group_items_by_type(order):
    """
    Grups the items of a change order in the following groups:

    - upsizing_items_in_window: item bought within the
      cancellation window which quantity have been increased
    - upsizing_items_out_window: item bought outside the
      cancellation window which have been quantity increased
    - downsizing_items_in_window: item bought within the
      cancellation window which quantity have been descreased
    - downsizing_items_out_window: item bought outside the
      cancellation window which have been quantity descreased
    Args:
        order (dict): the change order is being processed.

    Returns:
        ItemGroups: a data class with the three item groups.
    """
    upsizing_items_in_window = filter(
        lambda line: line["quantity"] > line["oldQuantity"]
        and in_cancellation_window(order, line),
        order["lines"],
    )
    upsizing_items_out_window = filter(
        lambda line: line["quantity"] > line["oldQuantity"]
        and not in_cancellation_window(order, line),
        order["lines"],
    )
    downsizing_items_in_window = filter(
        lambda line: line["quantity"] < line["oldQuantity"]
        and in_cancellation_window(order, line),
        order["lines"],
    )
    downsizing_items_out_window = filter(
        lambda line: line["quantity"] < line["oldQuantity"]
        and not in_cancellation_window(order, line),
        order["lines"],
    )

    return ItemGroups(
        list(upsizing_items_in_window),
        list(upsizing_items_out_window),
        list(downsizing_items_in_window),
        list(downsizing_items_out_window),
    )


def get_adobe_line_item_by_subscription_id(line_items, subscription_id):
    """
    Get the line item from an Adobe order which subscription id match the
    one given as an argument.

    Args:
        line_items (list): List of order line items.
        subscription_id (str): Identifier of the subscription to search.

    Returns:
        dict: the line item corresponding to the given subscription id.
    """
    return find_first(
        lambda item: item["subscriptionId"] == subscription_id,
        line_items,
    )


def is_new_customer(source):
    return (
        get_ordering_parameter(
            source,
            PARAM_AGREEMENT_TYPE,
        ).get("value")
        == "New"
    )


def set_parameter_visible(order, param_external_id):
    updated_order = copy.deepcopy(order)
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["constraints"] = {
        "hidden": False,
        "optional": param_external_id in OPTIONAL_CUSTOMER_ORDER_PARAMS,
    }
    return updated_order


def set_parameter_hidden(order, param_external_id):
    updated_order = copy.deepcopy(order)
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["constraints"] = {
        "hidden": True,
        "optional": True,
    }
    return updated_order


def set_adobe_3yc_enroll_status(order, enroll_status):
    updated_order = copy.deepcopy(order)
    customer_ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_3YC_ENROLL_STATUS,
    )
    customer_ff_param["value"] = enroll_status
    return updated_order
