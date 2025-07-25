import copy

from django.conf import settings
from mpt_extension_sdk.runtime.djapp.conf import get_for_product

from adobe_vipm.flows.constants import STATUS_MARKET_SEGMENT_PENDING, Param
from adobe_vipm.flows.utils.parameter import get_fulfillment_parameter


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
        Param.MARKET_SEGMENT_ELIGIBILITY_STATUS,
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
        Param.MARKET_SEGMENT_ELIGIBILITY_STATUS,
    )
    ff_param["value"] = STATUS_MARKET_SEGMENT_PENDING
    return updated_order
