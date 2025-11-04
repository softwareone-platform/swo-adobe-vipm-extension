import logging
import traceback
from collections.abc import Callable
from typing import Any

from mpt_extension_sdk.mpt_http.base import MPTClient

from adobe_vipm.flows.constants import OrderType
from adobe_vipm.flows.utils import (
    notify_unhandled_exception_in_teams,
    strip_trace_id,
    update_parameters_visibility,
)
from adobe_vipm.flows.utils.order import reset_order_error
from adobe_vipm.flows.utils.parameter import reset_ordering_parameters_error
from adobe_vipm.flows.utils.validation import is_migrate_customer, is_reseller_change
from adobe_vipm.flows.validation.change import validate_change_order
from adobe_vipm.flows.validation.purchase import validate_purchase_order
from adobe_vipm.flows.validation.termination import validate_termination_order
from adobe_vipm.flows.validation.transfer import validate_reseller_change, validate_transfer

logger = logging.getLogger(__name__)


def copy_order_without_errors(order: dict[str, Any]) -> dict[str, Any]:
    """Creates a clean copy of the order by removing any previous validation errors.

    Args:
        order: The order dictionary to clean.

    Returns:
        A copy of the order with all error states reset.

    """
    order = reset_ordering_parameters_error(order)
    return reset_order_error(order)


def get_purchase_order_validator(order: dict) -> Callable:
    """Get purchase order validator.

    Args:
        order: The order dictionary

    Returns:
        A validator callable or None if the order type is not supported.

    """
    if is_migrate_customer(order):
        return validate_transfer
    if is_reseller_change(order):
        return validate_reseller_change

    return validate_purchase_order


def get_validator_by_order_type(order: dict[str, Any]) -> Callable | None:
    """Get the validator function for the given order type.

    Args:
        order: The order dictionary

    Returns:
        A validator callable or None if the order type is not supported.

    """
    match order["type"]:
        case OrderType.PURCHASE:
            return get_purchase_order_validator(order)
        case OrderType.CHANGE:
            return validate_change_order
        case OrderType.TERMINATION:
            return validate_termination_order
        case _:
            return None


def validate_order(mpt_client: MPTClient, order: dict[str, Any]) -> dict[str, Any]:
    """
    Performs the validation of a draft order.

    Args:
        mpt_client: The client used to consume the MPT API.
        order: The order to validate

    Returns:
        The validated order.

    """
    order = copy_order_without_errors(order)

    validator = get_validator_by_order_type(order)
    if validator is None:
        logger.info("Validation of order %s succeeded without errors", order["id"])
        return order

    try:
        has_errors, order = validator(mpt_client, order)
    except Exception:
        notify_unhandled_exception_in_teams(
            "validation", order["id"], strip_trace_id(traceback.format_exc())
        )
        raise
    else:
        order = update_parameters_visibility(order)
        suffix_error_msg = "with errors" if has_errors else "without errors"
        logger.info("Validation of order %s succeeded %s", order["id"], suffix_error_msg)
        return order
