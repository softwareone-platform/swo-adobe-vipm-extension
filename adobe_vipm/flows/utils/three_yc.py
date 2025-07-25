import copy

from adobe_vipm.flows.constants import Param
from adobe_vipm.flows.utils.parameter import get_fulfillment_parameter, get_ordering_parameter


def set_adobe_3yc_enroll_status(order: dict, enroll_status: str) -> dict:
    """
    Sets Adobe 3YC status back to the order.

    Args:
        order: MPT order.
        enroll_status: Adobe 3YC enrollment status

    Returns:
        Update order
    """
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        Param.THREE_YC_ENROLL_STATUS,
    )
    ff_param["value"] = enroll_status
    return updated_order


def set_adobe_3yc_commitment_request_status(order: dict, status: str) -> dict:
    """
    Sets Adobe 3YC request status back to the order.

    Args:
        order: MPT order.
        status: Adobe 3YC request status

    Returns:
        Update order
    """
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        Param.THREE_YC_COMMITMENT_REQUEST_STATUS,
    )
    ff_param["value"] = status
    return updated_order


# TODO: probably we should operate always with date/time in the code
# and have conversion to proper datetime string inside the SDK
def set_adobe_3yc_start_date(order: dict, start_date: str) -> dict:
    """
    Sets Adobe 3YC start date back to the order.

    Args:
        order: MPT order.
        start_date: Adobe 3YC start date

    Returns:
        Update order
    """
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        Param.THREE_YC_START_DATE,
    )
    ff_param["value"] = start_date
    return updated_order


def set_adobe_3yc_end_date(order: dict, end_date: str) -> dict:
    """
    Sets Adobe 3YC end date back to the order.

    Args:
        order: MPT order.
        end_date: Adobe 3YC end date

    Returns:
        Update order
    """
    updated_order = copy.deepcopy(order)
    ff_param = get_fulfillment_parameter(
        updated_order,
        Param.THREE_YC_END_DATE,
    )
    ff_param["value"] = end_date
    return updated_order


# TODO: checkbox in MPT has specific structure of parameter. Worth to wrap it in SDK
def set_adobe_3yc(order: dict, value: str) -> dict:
    """
    Sets Adobe 3YC checkbox.

    Args:
        order: MPT order.
        value: Checkbox value

    Returns:
        Update order
    """
    updated_order = copy.deepcopy(order)
    ff_param = get_ordering_parameter(
        updated_order,
        Param.THREE_YC,
    )
    ff_param["value"] = value
    return updated_order


def set_adobe_3yc(order, value):
    updated_order = copy.deepcopy(order)
    ff_param = get_ordering_parameter(
        updated_order,
        PARAM_3YC,
    )
    ff_param["value"] = value
    return updated_order


def get_3yc_fulfillment_parameters(order_or_agreement: dict) -> list[str]:
    """
    Gets list of 3YC parameters from order or agreement.

    It includes THREE_YC_END_DATE, THREE_YC_ENROLL_STATUS, THREE_YC_START_DATE parameters

    Args:
        order_or_agreement: MPT order or MPT agreement.

    Returns:
        List of parameters' values
    """
    three_yc_fulfillment_parameters = [
        Param.THREE_YC_END_DATE,
        Param.THREE_YC_ENROLL_STATUS,
        Param.THREE_YC_START_DATE,
    ]

    return [
        get_fulfillment_parameter(order_or_agreement, param_external_id)
        for param_external_id in three_yc_fulfillment_parameters
    ]
