import copy

from adobe_vipm.adobe.constants import (
    OfferType,
)
from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.utils.date import is_within_last_two_weeks
from adobe_vipm.flows.utils.parameter import (
    get_fulfillment_parameter,
    get_ordering_parameter,
)
from adobe_vipm.utils import find_first


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
        Param.COMPANY_NAME,
        Param.ADDRESS,
        Param.CONTACT,
        Param.THREE_YC,
        Param.THREE_YC_CONSUMABLES,
        Param.THREE_YC_LICENSES,
    ):
        param = get_ordering_parameter(
            order,
            param_external_id,
        )
        customer_data[param_external_id] = param.get("value")

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


def get_company_name(source):
    return get_ordering_parameter(
        source,
        Param.COMPANY_NAME,
    ).get("value")


def get_adobe_customer_id(source):
    """
    Get the Adobe customer identifier from the corresponding fulfillment
    parameter or None if it is not set.

    Args:
        source (dict): The business object from which the customer id
        should be retrieved.

    Returns:
        str: The Adobe customer identifier or None if it isn't set.
    """
    param = get_fulfillment_parameter(
        source,
        Param.CUSTOMER_ID,
    )
    return param.get("value")


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
        Param.CUSTOMER_ID,
    )
    customer_ff_param["value"] = customer_id
    return updated_order


def get_customer_licenses_discount_level(customer):
    licenses_discount = find_first(
        lambda x: x["offerType"] == OfferType.LICENSE, customer["discounts"]
    )
    return licenses_discount["level"]


def get_customer_consumables_discount_level(customer):
    licenses_discount = find_first(
        lambda x: x["offerType"] == OfferType.CONSUMABLES, customer["discounts"]
    )
    return licenses_discount["level"]


def is_new_customer(source):
    param = get_ordering_parameter(
        source,
        Param.AGREEMENT_TYPE,
    )
    return param.get("value") == "New"


def get_global_customer(order):
    """
    Get the globalCustomer parameter from the order.
    Args:
        order (dict): The order to update.

    Returns:
        string: The value of the globalCustomer parameter.
    """
    global_customer_param = get_fulfillment_parameter(
        order,
        Param.GLOBAL_CUSTOMER,
    )
    return global_customer_param.get("value")


def set_global_customer(order, global_sales_enabled):
    """
    Set the globalCustomer parameter on the order.
    Args:
        order (dict): The order to update.
        global_sales_enabled (string): The value to set.

    Returns:
        dict: The updated order.
    """
    updated_order = copy.deepcopy(order)
    global_customer_param = get_fulfillment_parameter(
        updated_order,
        Param.GLOBAL_CUSTOMER,
    )
    global_customer_param["value"] = [global_sales_enabled]
    return updated_order


def is_within_coterm_window(customer):
    """
    Checks if the current date is within the last two weeks before the cotermination date.

    Returns:
        bool: True if within the window, False otherwise
    """
    return customer.get("cotermDate") and is_within_last_two_weeks(customer["cotermDate"])


def has_coterm_date(customer):
    """
    Checks if the customer has a cotermination date.

    Returns:
        bool: True if cotermination date exists, False otherwise
    """
    return bool(customer.get("cotermDate"))
