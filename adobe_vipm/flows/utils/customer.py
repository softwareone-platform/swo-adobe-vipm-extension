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


def get_customer_data(order: dict) -> dict:
    """
    Returns a customer data extracted from the corresponding ordering parameters.

    Args:
        order: The order from which the customer data must be retrieved.

    Returns:
        Customer data.
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


def set_customer_data(order: dict, customer_data: dict) -> dict:
    """
    Set the ordering parameters with the customer data.

    Args:
        order: The order for which the parameters must be set.
        customer_data: the customer data that must be set

    Returns:
        dict: Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    for param_external_id, value in customer_data.items():
        get_ordering_parameter(
            updated_order,
            param_external_id,
        )["value"] = value
    return updated_order


def get_company_name(source: dict) -> str | None:
    """
    Retrieves company name from COMPANY_NAME parameter.

    Args:
        source: MPT order or agreement.

    Returns:
        Company name.
    """
    return get_ordering_parameter(
        source,
        Param.COMPANY_NAME,
    ).get("value")


def get_adobe_customer_id(source: dict) -> str | None:
    """
    Get the Adobe customer identifier from the corresponding fulfillment parameter.

    Args:
        source: The business object from which the customer id should be retrieved.

    Returns:
        The Adobe customer identifier or None if it isn't set.
    """
    param = get_fulfillment_parameter(
        source,
        Param.CUSTOMER_ID,
    )
    return param.get("value")


def set_adobe_customer_id(order: dict, customer_id: str) -> dict:
    """
    Sets Adobe customer id to the CUSTOMER_ID order parameter.

    Args:
        order: MPT order.
        customer_id: Adobe customer id.

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    customer_ff_param = get_fulfillment_parameter(
        updated_order,
        Param.CUSTOMER_ID,
    )
    customer_ff_param["value"] = customer_id
    return updated_order


def get_customer_licenses_discount_level(customer: dict) -> int:
    """
    Retrieves customer licensees discount level from Adobe Customer.

    Args:
        customer: Adobe customer dictionary.

    Returns:
        Adobe discount level for licensees.
    """
    licenses_discount = find_first(
        lambda x: x["offerType"] == OfferType.LICENSE, customer["discounts"]
    )
    return licenses_discount["level"]


def get_customer_consumables_discount_level(customer: dict) -> int:
    """
    Retrieves customer consumables discount level from Adobe Customer.

    Args:
        customer: Adobe customer dictionary.

    Returns:
        Adobe discount level for consumables.
    """
    licenses_discount = find_first(
        lambda x: x["offerType"] == OfferType.CONSUMABLES, customer["discounts"]
    )
    return licenses_discount["level"]


def is_new_customer(source: dict) -> bool:
    """
    Checks if provided order or agreement has agreement type parameter setup to New.

    Means the order is created for the new customer.

    Args:
        source: MPT order or agreement.

    Returns:
        True if parameter in order or agreement is set to New value.
    """
    param = get_ordering_parameter(
        source,
        Param.AGREEMENT_TYPE,
    )
    return param.get("value") == "New"


def get_global_customer(order: dict) -> list[str] | None:
    """
    Get the globalCustomer parameter from the order.

    Args:
        order: MPT order.

    Returns:
        The value of the globalCustomer parameter.
    """
    global_customer_param = get_fulfillment_parameter(
        order,
        Param.GLOBAL_CUSTOMER,
    )
    return global_customer_param.get("value")


def set_global_customer(order: dict, global_sales_enabled: str) -> dict:
    """
    Set the globalCustomer parameter on the order.

    Args:
        order: The order to update.
        global_sales_enabled: The value to set.

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    global_customer_param = get_fulfillment_parameter(
        updated_order,
        Param.GLOBAL_CUSTOMER,
    )
    global_customer_param["value"] = [global_sales_enabled]
    return updated_order


def is_within_coterm_window(customer: dict) -> bool:
    """
    Checks if the current date is within the last two weeks before the cotermination date.

    Args:
        customer: Adobe customer.

    Returns:
        True if within the window, False otherwise
    """
    return customer.get("cotermDate") and is_within_last_two_weeks(customer["cotermDate"])


def has_coterm_date(customer: dict) -> bool:
    """
    Checks if the customer has a cotermination date.

    Args:
        customer: Adobe customer.

    Returns:
        True if cotermination date exists, False otherwise
    """
    return bool(customer.get("cotermDate"))
