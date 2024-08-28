import logging
import traceback

from adobe_vipm.adobe.client import get_adobe_client
from adobe_vipm.adobe.errors import AdobeAPIError
from adobe_vipm.flows.constants import ERR_ADOBE_ERROR
from adobe_vipm.flows.helpers import (
    populate_order_info,
    prepare_customer_data,
    update_purchase_prices,
)
from adobe_vipm.flows.utils import (
    is_change_order,
    is_purchase_order,
    is_purchase_validation_enabled,
    is_transfer_order,
    is_transfer_validation_enabled,
    notify_unhandled_exception_in_teams,
    reset_order_error,
    reset_ordering_parameters_error,
    set_order_error,
    strip_trace_id,
    update_parameters_visibility,
)
from adobe_vipm.flows.validation.change import validate_change_order
from adobe_vipm.flows.validation.purchase import (
    validate_customer_data,
    validate_duplicate_lines,
)
from adobe_vipm.flows.validation.transfer import validate_transfer

logger = logging.getLogger(__name__)


def validate_order(client, order):
    """
    Performs the validation of a draft order.

    Args:
        mpt_client (MPTClient): The client used to consume the MPT API.
        order (dict): The order to validate

    Returns:
        dict: The validated order.
    """
    try:
        has_errors = False

        if is_purchase_order(order):
            adobe_client = get_adobe_client()
            order = populate_order_info(client, order)
            order = reset_ordering_parameters_error(order)
            order = reset_order_error(order)
            order, customer_data = prepare_customer_data(client, order)
            if is_purchase_validation_enabled(order):
                has_errors, order = validate_customer_data(order, customer_data)
                if not has_errors and order["lines"]:
                    has_errors, order = validate_duplicate_lines(order)
                if not has_errors and order["lines"]:
                    try:
                        order = update_purchase_prices(adobe_client, order)
                    except AdobeAPIError as e:
                        order = set_order_error(
                            order, ERR_ADOBE_ERROR.to_dict(details=str(e))
                        )
                        has_errors = True

        elif is_change_order(order) and order["lines"]:
            has_errors, order = validate_change_order(client, order)
        elif is_transfer_order(order) and is_transfer_validation_enabled(
            order
        ):  # pragma: no branch
            adobe_client = get_adobe_client()
            order = populate_order_info(client, order)
            order = reset_ordering_parameters_error(order)
            order = reset_order_error(order)
            has_errors, order = validate_transfer(client, adobe_client, order)

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
