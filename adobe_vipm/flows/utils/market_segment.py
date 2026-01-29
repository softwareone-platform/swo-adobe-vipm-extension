import copy

from django.conf import settings
from mpt_extension_sdk.runtime.djapp.conf import get_for_product

from adobe_vipm.flows.constants import (
    MARKET_SEGMENT_LARGE_GOVERNMENT_AGENCY,
    STATUS_MARKET_SEGMENT_PENDING,
    Param,
)
from adobe_vipm.flows.utils.parameter import get_fulfillment_parameter, get_ordering_parameter


def get_market_segment(product_id: str) -> str:
    """
    Retrieves Adobe market segment based on provided Product Id.

    Information is retrieved from the configuration mapping provided in PRODUCT_SEGMENT.

    Args:
        product_id: MPT product id.

    Returns:
        Adobe market segment.
    """
    return get_for_product(settings, "PRODUCT_SEGMENT", product_id)


def is_large_government_agency_type(product_id: str) -> bool:
    """
    Checks if the product is a Large Government Agency product.

    Args:
        product_id: MPT product id.

    Returns:
        True if the product is a Large Government Agency product, False otherwise.
    """
    return (
        get_for_product(settings, "PRODUCT_SEGMENT", product_id)
        == MARKET_SEGMENT_LARGE_GOVERNMENT_AGENCY
    )


def get_market_segment_eligibility_status(order: dict) -> str | None:
    """
    Retrieves eligibility status parameter value from order.

    Args:
        order: MPT order.

    Returns:
        Value of the parameter.
    """
    return get_fulfillment_parameter(
        order,
        Param.MARKET_SEGMENT_ELIGIBILITY_STATUS.value,
    ).get("value")


def set_market_segment_eligibility_status_pending(order: dict) -> dict:
    """
    Sets eligibility status parameter value to pending.

    Args:
        order: MPT order.

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        Param.MARKET_SEGMENT_ELIGIBILITY_STATUS.value,
    )
    ff_param["value"] = STATUS_MARKET_SEGMENT_PENDING
    return updated_order


def get_agency_type(order) -> str:
    """
    Retrieves market sub segments based on provided order.

    Args:
        order: MPT order.

    Returns:
        Market sub segments.
    """
    return get_ordering_parameter(order, Param.AGENCY_TYPE.value).get("value")
