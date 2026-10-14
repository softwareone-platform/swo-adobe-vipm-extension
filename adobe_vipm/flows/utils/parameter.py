import copy
import functools
import json
from typing import Any

from django.conf import settings
from mpt_extension_sdk.mpt_http.utils import find_first
from mpt_extension_sdk.runtime.djapp.conf import get_for_product

from adobe_vipm.adobe.utils import is_flex_discount_applied
from adobe_vipm.flows.constants import (
    AGREEMENT_VISIBLE_PARAMETERS,
    PARAM_NEW_CUSTOMER_PARAMETERS,
    PARAM_OPTIONAL_CUSTOMER_ORDER,
    TRANSFER_CUSTOMER_PARAMETERS,
    AgreementType,
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


def set_ordering_parameter_error(
    order: dict,
    param_external_id: str,
    error: dict,
    *,
    required=True,
) -> dict:
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


def reset_ordering_parameters_error(order: dict) -> dict:
    """
    Reset errors for all ordering parameters.

    Args:
        order: The order that contains the parameter.

    Returns:
        Updated order.
    """
    updated_order = copy.deepcopy(order)

    for param in updated_order["parameters"][Param.PHASE_ORDERING.value]:
        param["error"] = None

    return updated_order


def update_parameters_visibility(order: dict) -> dict:
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
    updated_order = copy.deepcopy(order)

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


def set_coterm_date(order: dict, coterm_date: str) -> dict:
    """
    Sets coterm date parameter in MPT order.

    Args:
        order: MPT order.
        coterm_date: coterm date value.

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    customer_ff_param = get_fulfillment_parameter(
        updated_order,
        Param.COTERM_DATE.value,
    )
    customer_ff_param["value"] = coterm_date
    return updated_order


def get_coterm_date(order: dict) -> str | None:
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


def update_ordering_parameter_value(order: dict, param_external_id: str, value: Any) -> dict:
    """
    Update ordering parameter value in MPT order.

    Args:
        order: MPT order.
        param_external_id: MPT parameter external id.
        value: parameter value.

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["value"] = value

    return updated_order


def update_fulfillment_parameter_value(order: dict, param_external_id: str, value: Any) -> dict:
    """
    Update fulfillment parameter value in MPT order.

    Args:
        order: MPT order.
        param_external_id: MPT parameter external id.
        value: parameter value.

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    param = get_fulfillment_parameter(
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


def get_switch_payload(source: dict) -> dict | None:
    """
    Get the mid-term upgrade (SWITCH) payload from the corresponding ordering parameter.

    Args:
        source: The business object from which the switch payload should be retrieved.

    Returns:
        The switch payload or None if it isn't set.
    """
    payload = get_ordering_parameter(source, Param.SWITCH_PAYLOAD.value).get("value")
    if not payload:
        return None
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def get_renewal_payload(source: dict) -> dict | None:
    """
    Get the at-anniversary renewal payload from the corresponding ordering parameter.

    Args:
        source: The business object from which the renewal payload should be retrieved.

    Returns:
        The renewal payload or None if it isn't set.
    """
    payload = get_ordering_parameter(source, Param.RENEWAL_PAYLOAD.value).get("value")
    if not payload:
        return None
    if isinstance(payload, str):
        return json.loads(payload)
    return payload


def set_parameter_visible(order: dict, param_external_id: str) -> dict:
    """
    Sets ordering parameter visibility.

    Args:
        order: MPT order.
        param_external_id: Parameter external id.

    Returns:
        Updated MPT order.
    """
    updated_order = copy.deepcopy(order)
    param = get_ordering_parameter(
        updated_order,
        param_external_id,
    )
    param["constraints"] = {
        "hidden": False,
        "required": param_external_id not in PARAM_OPTIONAL_CUSTOMER_ORDER,
    }
    return updated_order


def set_parameter_hidden(order: dict, param_external_id: str) -> dict:
    """
    Sets ordering parameter with param_external_id hidden in MPT order.

    Args:
        order: MPT order.
        param_external_id: Parameter external id.

    Returns:
        Update MPT order.
    """
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


def get_retry_count(order: dict) -> str | None:
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
    agreement_type_value = agreement_type.get("value") or AgreementType.NEW.value
    market_segment = get_for_product(settings, "PRODUCT_SEGMENT", order["product"]["id"])
    visible_params = list(AGREEMENT_VISIBLE_PARAMETERS.get(agreement_type_value, []))
    visible_params.extend(AGREEMENT_VISIBLE_PARAMETERS.get(market_segment, []))
    updated_order = copy.deepcopy(order)  # noqa: WPS204

    for phase in (Param.PHASE_ORDERING.value, Param.PHASE_FULFILLMENT.value):
        for param in updated_order["parameters"][phase]:
            if "constraints" not in param:
                param["constraints"] = {}
            param["constraints"]["hidden"] = param["externalId"] not in visible_params

    return updated_order


def _get_applied_flex_discount_codes(line: dict, requested_codes: dict | None) -> list[str]:
    """
    Codes Adobe applied on the line (a result other than SUCCESS was not applied).

    When the codes the order requested per line are known, only the requested
    code counts: a discount Adobe auto-applied on its own is not something the
    order redeemed.
    """
    applied = [
        flex_discount["code"]
        for flex_discount in line.get("flexDiscounts") or []
        if is_flex_discount_applied(flex_discount)
    ]
    if requested_codes is None:
        return applied
    requested_code = requested_codes.get(line.get("extLineItemNumber"))
    return [code for code in applied if code == requested_code]


def set_flex_discounts_parameter(
    order: dict, adobe_order: dict, requested_codes: dict | None = None, *, pending: bool = False
) -> dict:
    """
    Save the flex discount codes applied by an Adobe order to the order parameter.

    The parameter is the per-order provenance record and the source of the
    redemption recording: it lists, per Adobe line, the codes Adobe applied
    (result SUCCESS), restricted to the code the order requested on the line
    when the requested codes are given (context.flex_discount_selection).

    Args:
        order: MPT order.
        adobe_order: Adobe order.
        requested_codes: Flex discount code requested per Adobe line number, None
            to record every applied code.
        pending: Store preview-confirmed proposals as requestedFlexDiscountCode
            until the committed order completes. Pending proposals are not redemptions.

    Returns:
        Updated MPT order.
    """
    flex_discounts = [
        {
            "extLineItemNumber": line.get("extLineItemNumber"),
            "offerId": line.get("offerId"),
            "subscriptionId": line.get("subscriptionId"),
            "flexDiscountCode": _get_applied_flex_discount_codes(line, requested_codes),
        }
        for line in adobe_order["lineItems"]
        if _get_applied_flex_discount_codes(line, requested_codes)
    ]
    if pending:
        for entry in flex_discounts:
            entry["requestedFlexDiscountCode"] = entry.pop("flexDiscountCode")[0]
    return update_fulfillment_parameter_value(
        order, Param.FLEXIBLE_DISCOUNTS.value, flex_discounts or None
    )


def get_flex_discounts_parameter(order: dict) -> list[dict]:
    """
    Read the flex discounts recorded on the order parameter.

    The parameter is a JSON parameter, so its value comes back either as the
    stored list or as its JSON string depending on the source of the order.

    Args:
        order: MPT order.

    Returns:
        list[dict]: The recorded entries ({extLineItemNumber, offerId,
        subscriptionId, flexDiscountCode}), empty when nothing was recorded.
    """
    value = get_fulfillment_parameter(order, Param.FLEXIBLE_DISCOUNTS.value).get("value")
    if isinstance(value, str):
        value = json.loads(value) if value.strip() else None
    return list(value or [])


def get_requested_flex_discount_codes(order: dict) -> dict[int, str]:
    """Read pending proposals or previously recorded codes for completion reconciliation."""
    requested_codes = {}
    for entry in get_flex_discounts_parameter(order):
        code = entry.get("requestedFlexDiscountCode")
        if not code:
            applied_codes = entry.get("flexDiscountCode") or []
            code = next(iter(applied_codes), None)
        if code:
            requested_codes[entry["extLineItemNumber"]] = code
    return requested_codes


def get_adobe_order_ids_created_parameter(order: dict) -> list[str]:
    """Return the Adobe order IDs persisted for Change orders as a list."""
    order_ids_param = get_ordering_parameter(order, Param.ADOBE_ORDER_IDS.value)
    return [
        order_id.strip()
        for order_id in (order_ids_param.get("value") or "").split(",")
        if order_id.strip()
    ]


def set_adobe_order_ids_created_parameter(context, order_ids: list[str | None]) -> dict:
    """Persist Adobe order IDs for Change orders as comma-separated values."""
    sanitized_order_ids = [
        order_id.strip() for order_id in order_ids if order_id and order_id.strip()
    ]
    if not sanitized_order_ids:
        return context.order

    order_ids_param = get_ordering_parameter(context.order, Param.ADOBE_ORDER_IDS.value)
    existing_order_ids = [
        order_id.strip()
        for order_id in (order_ids_param.get("value") or "").split(",")
        if order_id.strip()
    ]
    merged_order_ids = list(dict.fromkeys(existing_order_ids + sanitized_order_ids))
    if merged_order_ids == existing_order_ids:
        return context.order

    adobe_order_ids = ",".join(merged_order_ids)
    if not order_ids_param:
        context.order.setdefault("parameters", {}).setdefault(
            Param.PHASE_ORDERING.value, []
        ).append({
            "externalId": Param.ADOBE_ORDER_IDS.value,
            "value": adobe_order_ids,
        })

    context.order = update_ordering_parameter_value(
        context.order, Param.ADOBE_ORDER_IDS.value, adobe_order_ids
    )

    return context.order
