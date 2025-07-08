import copy
import functools

from adobe_vipm.flows.constants import (
    Param,
)
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


get_ordering_parameter = functools.partial(get_parameter, Param.PHASE_ORDERING)

get_fulfillment_parameter = functools.partial(get_parameter, Param.PHASE_FULFILLMENT)


def set_ordering_parameter_error(order, param_external_id, error, required=True):
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
        "required": required,
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

    for param in updated_order["parameters"][Param.PHASE_ORDERING]:
        param["error"] = None

    return updated_order


def update_parameters_visibility(order):
    from adobe_vipm.flows.utils.customer import is_new_customer

    if is_new_customer(order):
        for param in Param.NEW_CUSTOMER_PARAMETERS:
            order = set_parameter_visible(order, param)
        order = set_parameter_hidden(order, Param.MEMBERSHIP_ID)
    else:
        for param in Param.NEW_CUSTOMER_PARAMETERS:
            order = set_parameter_hidden(order, param)
        order = set_parameter_visible(order, Param.MEMBERSHIP_ID)
    return order


def is_ordering_param_required(source, param_external_id):
    param = get_ordering_parameter(source, param_external_id)
    return (param.get("constraints", {}) or {}).get("required", False)


def set_coterm_date(order, coterm_date):
    updated_order = copy.deepcopy(order)
    customer_ff_param = get_fulfillment_parameter(
        updated_order,
        Param.COTERM_DATE,
    )
    customer_ff_param["value"] = coterm_date
    return updated_order


def get_coterm_date(order):
    return get_fulfillment_parameter(
        order,
        Param.COTERM_DATE,
    ).get("value")


def update_ordering_parameter_value(order, param_external_id, value):
    updated_order = copy.deepcopy(order)
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["value"] = value

    return updated_order


def get_adobe_membership_id(source):
    """
    Get the Adobe membership identifier from the corresponding ordering
    parameter or None if it is not set.

    Args:
        source (dict): The business object from which the membership id
        should be retrieved.

    Returns:
        str: The Adobe membership identifier or None if it isn't set.
    """
    param = get_ordering_parameter(
        source,
        Param.MEMBERSHIP_ID,
    )
    return param.get("value")


def set_parameter_visible(order, param_external_id):
    updated_order = copy.deepcopy(order)
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["constraints"] = {
        "hidden": False,
        "required": param_external_id not in Param.OPTIONAL_CUSTOMER_ORDER,
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
        "required": False,
    }
    return updated_order


def get_retry_count(order):
    """
    Gets RETRY_COUNT parameter
    Args:
        order (dict): The order that contains the retry count fulfillment
        parameter.

    Returns:
        str: retry count. None if parameter doesn't exist
    """
    param = find_first(
        lambda x: x["externalId"] == Param.RETRY_COUNT,
        order["parameters"]["fulfillment"],
    )

    if not param:
        return

    return param["value"] if param.get("value") else ""
