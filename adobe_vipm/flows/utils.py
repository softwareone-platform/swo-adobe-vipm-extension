import copy

from adobe_vipm.flows.constants import (
    ORDER_TYPE_PURCHASE,
    PARAM_ADDRESS,
    PARAM_COMPANY_NAME,
    PARAM_CONTACT,
    PARAM_CUSTOMER_ID,
    PARAM_MEMBERSHIP_ID,
    PARAM_PREFERRED_LANGUAGE,
    PARAM_RETRY_COUNT,
)
from adobe_vipm.utils import find_first


def get_parameter(order, parameter_phase, parameter_name):
    return find_first(
        lambda x: x["name"] == parameter_name,
        order["parameters"][parameter_phase],
        default={},
    )


def is_purchase_order(order):
    return order["type"] == ORDER_TYPE_PURCHASE and not get_parameter(
        order,
        "fulfillment",
        PARAM_MEMBERSHIP_ID,
    ).get("value")


def get_adobe_customer_id(source):
    return get_parameter(
        source,
        "fulfillment",
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
    customer_ff_param = get_parameter(
        updated_order,
        "fulfillment",
        PARAM_CUSTOMER_ID,
    )
    customer_ff_param["value"] = customer_id
    return updated_order


def get_adobe_order_id(order):
    return order.get("externalIDs", {}).get("vendor")


def set_adobe_order_id(order, adobe_order_id):
    updated_order = copy.deepcopy(order)
    updated_order["externalIDs"] = updated_order.get("externalIDs", {}) | {"vendor": adobe_order_id}
    return updated_order


def get_customer_data(order):
    customer_data = {}
    for param_name in (
        PARAM_COMPANY_NAME,
        PARAM_PREFERRED_LANGUAGE,
        PARAM_ADDRESS,
        PARAM_CONTACT,
    ):
        customer_data[param_name] = get_parameter(
            order,
            "order",
            param_name,
        ).get("value")

    return customer_data


def set_customer_data(order, customer_data):
    updated_order = copy.deepcopy(order)
    for param_name, value in customer_data.items():
        get_parameter(
            updated_order,
            "order",
            param_name,
        )["value"] = value
    return updated_order


def set_ordering_parameter_error(order, param_name, error):
    updated_order = copy.deepcopy(order)
    get_parameter(
        updated_order,
        "order",
        param_name,
    )["error"] = error
    return updated_order


def get_order_item(order, line_number):
    return find_first(
        lambda item: line_number == item["lineNumber"],
        order["items"],
    )


def increment_retry_count(order):
    updated_order = copy.deepcopy(order)
    param = get_parameter(
        updated_order,
        "fulfillment",
        PARAM_RETRY_COUNT,
    )

    param["value"] = str(int(param["value"]) + 1) if param["value"] else "1"
    return updated_order


def reset_retry_count(order):
    updated_order = copy.deepcopy(order)
    param = get_parameter(
        updated_order,
        "fulfillment",
        PARAM_RETRY_COUNT,
    )
    param["value"] = "0"
    return updated_order


def get_retry_count(order):
    return int(
        get_parameter(
            order,
            "fulfillment",
            PARAM_RETRY_COUNT,
        ).get("value", "0")
        or "0",
    )


def get_subscription_by_line_and_item_id(subscriptions, line_number, product_item_id):
    for subscription in subscriptions:
        item = find_first(
            lambda x: x["lineNumber"] == line_number and x["productItemId"] == product_item_id,
            subscription["items"],
        )

        if item:
            return subscription
