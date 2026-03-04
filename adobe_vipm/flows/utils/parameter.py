import copy
import functools
from typing import Any

from django.conf import settings
from mpt_extension_sdk.mpt_http.utils import find_first
from mpt_extension_sdk.runtime.djapp.conf import get_for_product

from adobe_vipm.flows.constants import (
    AGREEMENT_VISIBLE_PARAMETERS,
    PARAM_NEW_CUSTOMER_PARAMETERS,
    PARAM_OPTIONAL_CUSTOMER_ORDER,
    TRANSFER_CUSTOMER_PARAMETERS,
    Param,
)


def get_parameter(parameter_phase: str, source: dict[str, Any], param_external_id: str) -> dict:
    """
    Returns a parameter of a given phase by its external identifier.

    Returns an empty dictionary if the parameter is not found.

    Args:
        parameter_phase: The phase of the parameter (ordering, fulfillment).
        source: The source business object from which the parameter should be extracted.
        param_external_id: The unique external identifier of the parameter.

    Returns:
        The parameter object or an empty dictionary if not found.
    """
    return find_first(
        lambda phase: phase["externalId"] == param_external_id,
        source["parameters"][parameter_phase],
        default={},
    )


get_ordering_parameter = functools.partial(get_parameter, Param.PHASE_ORDERING.value)

get_fulfillment_parameter = functools.partial(get_parameter, Param.PHASE_FULFILLMENT.value)


def _copy_order(order: dict[str, Any]) -> dict[str, Any]:
    """Returns a deep copy of the order."""
    return copy.deepcopy(order)


def set_ordering_parameter_error(
    order: dict[str, Any],
    param_external_id: str,
    error: dict[str, Any],
    *,
    required=True,
) -> dict[str, Any]:
    """
    Set a validation error on an ordering parameter.

    Args:
        order: The order that contains the parameter.
        param_external_id: The external identifier of the parameter.
        error: The error (id, message) that must be set.
        required: Sets parameter required field.

    Returns:
        Updated MPT order.
    """
    updated_order = _copy_order(order)  # noqa: WPS204
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


def reset_ordering_parameters_error(order: dict[str, Any]) -> dict[str, Any]:
    """
    Reset errors for all ordering parameters.

    Args:
        order: The order that contains the parameter.

    Returns:
        Updated order.
    """
    updated_order = _copy_order(order)  # noqa: WPS204

    for param in updated_order["parameters"][Param.PHASE_ORDERING.value]:
        param["error"] = None

    return updated_order


def update_parameters_visibility(order: dict[str, Any]) -> dict[str, Any]:
    """
    Update order parameters visibility based on choosen parameter of agreement type.

    If it is new customer order sets parameters that are requied for new customer to visible
    and required. Otherise hide them and unmark as required.

    Args:
        order: MPT order.

    Returns:
        Updated MPT order.
    """
    agreement_type = get_ordering_parameter(order, Param.AGREEMENT_TYPE.value)
    agreement_value = (agreement_type.get("value") or "").lower()
    updated_order = _copy_order(order)  # noqa: WPS204

    parameters_map = {
        "new": {
            "visible": PARAM_NEW_CUSTOMER_PARAMETERS,
            "hidden": (*TRANSFER_CUSTOMER_PARAMETERS, *(Param.MEMBERSHIP_ID.value,)),
        },
        "migrate": {
            "visible": [Param.MEMBERSHIP_ID.value],
            "hidden": (*PARAM_NEW_CUSTOMER_PARAMETERS, *TRANSFER_CUSTOMER_PARAMETERS),
        },
        "transfer": {
            "visible": TRANSFER_CUSTOMER_PARAMETERS,
            "hidden": (*PARAM_NEW_CUSTOMER_PARAMETERS, *(Param.MEMBERSHIP_ID.value,)),
        },
    }
    param_config = parameters_map.get(agreement_value, {})
    for param in param_config.get("visible", []):
        updated_order = set_parameter_visible(updated_order, param)
    for param in param_config.get("hidden", []):
        updated_order = set_parameter_hidden(updated_order, param)

    return updated_order


def is_ordering_param_required(source: dict, param_external_id: str) -> bool:
    """
    Checks if ordering parameter is required.

    Args:
        source: MPT order or agreement.
        param_external_id: Parameter external id.

    Returns:
        If the parameter is set as required in provided order or agreement.
    """
    param = get_ordering_parameter(source, param_external_id)
    return (param.get("constraints", {}) or {}).get("required", False)


def set_coterm_date(order: dict[str, Any], coterm_date: str) -> dict[str, Any]:
    """
    Sets coterm date parameter in MPT order.

    Args:
        order: MPT order.
        coterm_date: coterm date value.

    Returns:
        Updated MPT order.
    """
    updated_order = _copy_order(order)  # noqa: WPS204
    customer_ff_param = get_fulfillment_parameter(
        updated_order,
        Param.COTERM_DATE.value,
    )
    customer_ff_param["value"] = coterm_date
    return updated_order


def get_coterm_date(order: dict[str, Any]) -> str | None:
    """
    Returns coterm date from MPT order coterm date parameter.

    Args:
        order: MPT order.

    Returns:
        Coterm date or None
    """
    return get_fulfillment_parameter(
        order,
        Param.COTERM_DATE.value,
    ).get("value")


def update_ordering_parameter_value(
    order: dict[str, Any], param_external_id: str, value: str
) -> dict[str, Any]:
    """
    Update ordering parameter value in MPT order.

    Args:
        order: MPT order.
        param_external_id: MPT parameter external id.
        value: parameter value.

    Returns:
        Updated MPT order.
    """
    updated_order = _copy_order(order)  # noqa: WPS204
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["value"] = value

    return updated_order


def get_adobe_membership_id(source: dict) -> str | None:
    """
    Get the Adobe membership id from the corresponding ordering parameter.

    Args:
        source: The business object from which the membership id should be retrieved.

    Returns:
        The Adobe membership identifier or None if it isn't set.
    """
    param = get_ordering_parameter(
        source,
        Param.MEMBERSHIP_ID.value,
    )
    return param.get("value")


def get_change_reseller_code(source):
    """
    Get the change reseller code from the corresponding ordering parameter.

    Args:
        source: The business object from which the change reseller code should be retrieved.

    Returns:
        The change reseller code or None if it isn't set.
    """
    param = get_ordering_parameter(
        source,
        Param.CHANGE_RESELLER_CODE,
    )
    return param.get("value")


def get_change_reseller_admin_email(source):
    """
    Get the admin email from the corresponding ordering parameter.

    Args:
        source: The business object from which the admin email should be retrieved.

    Returns:
        The admin email or None if it isn't set.
    """
    param = get_ordering_parameter(
        source,
        Param.ADOBE_CUSTOMER_ADMIN_EMAIL,
    )
    return param.get("value")


def set_parameter_visible(order: dict[str, Any], param_external_id: str) -> dict[str, Any]:
    """
    Sets ordering parameter visibility.

    Args:
        order: MPT order.
        param_external_id: Parameter external id.

    Returns:
        Updated MPT order.
    """
    updated_order = _copy_order(order)  # noqa: WPS204
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["constraints"] = {
        "hidden": False,
        "required": param_external_id not in PARAM_OPTIONAL_CUSTOMER_ORDER,
    }
    return updated_order


def set_parameter_hidden(order: dict[str, Any], param_external_id: str) -> dict[str, Any]:
    """
    Sets ordering parameter with param_external_id hidden in MPT order.

    Args:
        order: MPT order.
        param_external_id: Parameter external id.

    Returns:
        Update MPT order.
    """
    updated_order = _copy_order(order)  # noqa: WPS204
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["constraints"] = {
        "hidden": True,
        "required": False,
    }
    return updated_order


def get_retry_count(order: dict[str, Any]) -> str | None:
    """
    Gets RETRY_COUNT parameter.

    Args:
        order: The order that contains the retry count fulfillment parameter.

    Returns:
        Retry count. None if parameter doesn't exist
    """
    param = find_first(
        lambda fulfillment: fulfillment["externalId"] == Param.RETRY_COUNT.value,
        order["parameters"]["fulfillment"],
    )

    if not param:
        return None

    return param["value"] if param.get("value") else ""


def update_agreement_params_visibility(
    order: dict[str, Any],
) -> dict[str, Any]:
    """Updates order parameters hidden constraint for ordering and fulfillment parameters.

    Sets the hidden constraint on each parameter based on the agreement type
    and market segment visibility rules. Parameters whose external ID is present
    in the visibility rules dictionary for the current agreement type and market
    segment are marked as visible; all others are marked as hidden.

    Args:
        order: MPT order.

    Returns:
        Updated MPT order with visibility constraints applied.
    """
    agreement_type = get_ordering_parameter(order, Param.AGREEMENT_TYPE.value)
    agreement_value = (agreement_type.get("value") or "").lower()
    market_segment = get_for_product(settings, "PRODUCT_SEGMENT", order["product"]["id"])
    visible_params = list(AGREEMENT_VISIBLE_PARAMETERS.get(agreement_value, []))
    visible_params.extend(AGREEMENT_VISIBLE_PARAMETERS.get(market_segment, []))
    updated_order = _copy_order(order)  # noqa: WPS204

    for phase in (Param.PHASE_ORDERING.value, Param.PHASE_FULFILLMENT.value):
        for param in updated_order["parameters"][phase]:
            param["constraints"] = {
                "hidden": param["externalId"] not in visible_params,
                "required": False,
            }

    return updated_order
