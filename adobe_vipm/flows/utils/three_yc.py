import copy

from adobe_vipm.flows.constants import (
    PARAM_3YC,
    PARAM_3YC_COMMITMENT_REQUEST_STATUS,
    PARAM_3YC_END_DATE,
    PARAM_3YC_ENROLL_STATUS,
    PARAM_3YC_START_DATE,
)
from adobe_vipm.flows.utils.parameter import get_fulfillment_parameter, get_ordering_parameter


def set_adobe_3yc_enroll_status(order, enroll_status):
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_3YC_ENROLL_STATUS,
    )
    ff_param["value"] = enroll_status
    return updated_order


def set_adobe_3yc_commitment_request_status(order, status):
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_3YC_COMMITMENT_REQUEST_STATUS,
    )
    ff_param["value"] = status
    return updated_order


def set_adobe_3yc_start_date(order, start_date):
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_3YC_START_DATE,
    )
    ff_param["value"] = start_date
    return updated_order


def set_adobe_3yc_end_date(order, end_date):
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        PARAM_3YC_END_DATE,
    )
    ff_param["value"] = end_date
    return updated_order


def set_adobe_3yc(order, value):
    updated_order = copy.deepcopy(order)
    ff_param = get_ordering_parameter(
        updated_order,
        PARAM_3YC,
    )
    ff_param["value"] = value
    return updated_order


def get_3yc_fulfillment_parameters(order_or_agreement):
    three_yc_fulfillment_parameters = [
        PARAM_3YC_END_DATE,
        PARAM_3YC_ENROLL_STATUS,
        PARAM_3YC_START_DATE,
    ]

    return [
        get_fulfillment_parameter(order_or_agreement, param_external_id)
        for param_external_id in three_yc_fulfillment_parameters
    ]
