import copy

from django.conf import settings
from mpt_extension_sdk.runtime.djapp.conf import get_for_product

from adobe_vipm.flows.constants import (
    PARAM_MARKET_SEGMENT_ELIGIBILITY_STATUS,
    STATUS_MARKET_SEGMENT_PENDING,
)
from adobe_vipm.flows.utils.parameter import get_fulfillment_parameter


def get_market_segment(product_id):
    return get_for_product(settings, "PRODUCT_SEGMENT", product_id)


def get_market_segment_eligibility_status(order):
    return get_fulfillment_parameter(
        order,
        PARAM_MARKET_SEGMENT_ELIGIBILITY_STATUS,
    ).get("value")

def set_market_segment_eligibility_status_pending(order):
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_MARKET_SEGMENT_ELIGIBILITY_STATUS,
    )
    ff_param["value"] = STATUS_MARKET_SEGMENT_PENDING
    return updated_order
