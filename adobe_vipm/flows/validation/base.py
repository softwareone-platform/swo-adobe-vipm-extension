import logging
import traceback

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.flows import constants
from adobe_vipm.flows.helpers import (
    populate_order_info,
)
from adobe_vipm.flows.utils import (
    is_transfer_order,
    is_transfer_validation_enabled,
    notify_unhandled_exception_in_teams,
    reset_order_error,
    reset_ordering_parameters_error,
    strip_trace_id,
    update_parameters_visibility,
)
from adobe_vipm.flows.validation.change import validate_change_order
from adobe_vipm.flows.validation.purchase import (
    validate_purchase_order,
)
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

        match order["type"]:
            case constants.ORDER_TYPE_PURCHASE:
                if is_transfer_order(order) and is_transfer_validation_enabled(
                    order
                ):
                    adobe_client = get_adobe_client()
                    order = populate_order_info(client, order)
                    order = reset_ordering_parameters_error(order)
                    order = reset_order_error(order)
                    has_errors, order = validate_transfer(client, adobe_client, order)
                else:
                    has_errors, order = validate_purchase_order(client, order)
            case constants.ORDER_TYPE_CHANGE:
                has_errors, order = validate_change_order(client, order)
            case constants.ORDER_TYPE_TERMINATION:
                has_errors, order = validate_termination_order(client, order)


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
