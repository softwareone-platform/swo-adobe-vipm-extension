import logging
import traceback

from adobe_vipm.flows.constants import OrderType
from adobe_vipm.flows.fulfillment.change import fulfill_change_order
from adobe_vipm.flows.fulfillment.configuration import fulfill_configuration_order
from adobe_vipm.flows.fulfillment.purchase import fulfill_purchase_order
from adobe_vipm.flows.fulfillment.reseller_transfer import fulfill_reseller_change_order
from adobe_vipm.flows.fulfillment.termination import fulfill_termination_order
from adobe_vipm.flows.fulfillment.transfer import fulfill_transfer_order
from adobe_vipm.flows.utils import notify_unhandled_exception_in_teams, strip_trace_id
from adobe_vipm.flows.utils.validation import is_migrate_customer, is_reseller_change

logger = logging.getLogger(__name__)


def _fulfill_purchase_order_router(client, order):
    if is_migrate_customer(order):
        return fulfill_transfer_order(client, order)
    if is_reseller_change(order):
        return fulfill_reseller_change_order(client, order)
    return fulfill_purchase_order(client, order)


def fulfill_order(client, order):
    """
    Fulfills an order of any type by processing the actions based on the provided parameters.

    Args:
        client (MPTClient): An instance of the client for consuming the MPT platform API.
        order (dict): The order that needs to be processed.

    Returns:
        None
    """
    logger.info("Start processing %s order %s", order["type"], order["id"])

    validators = {
        OrderType.PURCHASE: _fulfill_purchase_order_router,
        OrderType.CHANGE: fulfill_change_order,
        OrderType.TERMINATION: fulfill_termination_order,
        OrderType.CONFIGURATION: fulfill_configuration_order,
    }

    try:
        if order["type"] in validators:
            validators[order.get("type")](client, order)
        else:
            logger.info("Order %s is not a valid order type", order["id"])
    except Exception:
        notify_unhandled_exception_in_teams(
            "fulfillment",
            order["id"],
            strip_trace_id(traceback.format_exc()),
        )
        raise
