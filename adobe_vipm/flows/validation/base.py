import logging
import traceback

from adobe_vipm.flows import constants
from adobe_vipm.flows.utils import (
    get_ordering_parameter,
    is_transfer_validation_enabled,
    notify_unhandled_exception_in_teams,
    strip_trace_id,
    update_parameters_visibility,
)
from adobe_vipm.flows.validation.change import validate_change_order
from adobe_vipm.flows.validation.purchase import validate_purchase_order
from adobe_vipm.flows.validation.termination import validate_termination_order
from adobe_vipm.flows.validation.transfer import validate_transfer

logger = logging.getLogger(__name__)


def validate_order(client, order):
    """
    Performs the validation of a draft order.

    Args:
        client (MPTClient): The client used to consume the MPT API.
        order (dict): The order to validate

    Returns:
        dict: The validated order.
    """
    try:
        has_errors = False
        agreement_type = get_ordering_parameter(order, constants.PARAM_AGREEMENT_TYPE).get("value")

        def validate_purchase_or_transfer(client, order):
            if agreement_type == "Migrate" and is_transfer_validation_enabled(order):
                return validate_transfer(client, order)
            else:
                return validate_purchase_order(client, order)

        validators = {
            constants.ORDER_TYPE_PURCHASE: validate_purchase_or_transfer,
            constants.ORDER_TYPE_CHANGE: validate_change_order,
            constants.ORDER_TYPE_TERMINATION: validate_termination_order,
        }

        if order["type"] in validators:
            has_errors, order = validators[order["type"]](client, order)

        order = update_parameters_visibility(order)

        if not order["lines"]:  # pragma: no cover
            del order["lines"]

        logger.info(
            f"Validation of order {order['id']} succeeded "
            f"with{'out' if not has_errors else ''} errors"
        )
        return order
    except Exception:
        notify_unhandled_exception_in_teams(
            "validation",
            order["id"],
            strip_trace_id(traceback.format_exc()),
        )
        raise
