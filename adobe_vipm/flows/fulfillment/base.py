import logging
import traceback

from adobe_vipm.flows import constants
from adobe_vipm.flows.fulfillment.change import fulfill_change_order
from adobe_vipm.flows.fulfillment.configuration import fulfill_configuration_order
from adobe_vipm.flows.fulfillment.purchase import fulfill_purchase_order
from adobe_vipm.flows.fulfillment.shared import start_processing_attempt
from adobe_vipm.flows.fulfillment.termination import fulfill_termination_order
from adobe_vipm.flows.fulfillment.transfer import fulfill_transfer_order
from adobe_vipm.flows.helpers import populate_order_info
from adobe_vipm.flows.utils import (
    is_transfer_order,
    notify_unhandled_exception_in_teams,
    strip_trace_id,
)

logger = logging.getLogger(__name__)


def fulfill_order(client, order):  # noqa: C901
    """
    Fulfills an order of any type by processing the actions based on the provided parameters.

    Args:
        client (MPTClient): An instance of the client for consuming the MPT platform API.
        order (dict): The order that needs to be processed.

    Returns:
        None
    """
    logger.info("Start processing %s order %s", order["type"], order["id"])
    try:
        match order["type"]:
            case constants.ORDER_TYPE_PURCHASE:
                if not is_transfer_order(order):
                    fulfill_purchase_order(client, order)
                else:
                    order = populate_order_info(client, order)
                    order = start_processing_attempt(client, order)
                    fulfill_transfer_order(client, order)
            case constants.ORDER_TYPE_CHANGE:
                fulfill_change_order(client, order)
            case constants.ORDER_TYPE_CONFIGURATION:
                fulfill_configuration_order(client, order)
            case constants.ORDER_TYPE_TERMINATION:
                fulfill_termination_order(client, order)
    except Exception:
        notify_unhandled_exception_in_teams(
            "fulfillment",
            order["id"],
            strip_trace_id(traceback.format_exc()),
        )
        raise
